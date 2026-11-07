"""OpenAI-compatible embeddings client (aiohttp).

Used by the memory module when org/bot-level embedding retrieval is enabled.
The client is deliberately small and dependency-injectable:

* ``base_url`` is a provider root (``https://api.openai.com``); ``/v1`` is
  appended automatically, so both roots and ``.../v1`` roots work.
* Inputs are sent in batches (``batch_size``) and the result is flattened in
  the caller's order.
* Every upstream/transport problem is normalised to :class:`MemoryApiError`
  whose ``message`` never contains the API key (safe to surface as a 502).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import aiohttp

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_BATCH_SIZE = 32
MAX_BATCH_SIZE = 256
MASKED_API_KEY = "••••••••"


class MemoryApiError(RuntimeError):
    """Normalised embedding/rerank upstream failure.

    ``status`` is the upstream HTTP status when one was received.  ``message``
    is already sanitised (no API key, no giant response dump) and is the only
    text callers may show to end users.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str = "upstream_error",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = int(status) if status is not None else None
        self.code = code
        self.detail = detail

    def public_message(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "status": self.status}


# --------------------------------------------------------------------------
# helpers shared with the rerank client
# --------------------------------------------------------------------------
def sanitize_text(text: Any, *, secret: str = "", limit: int = 240) -> str:
    """Collapse whitespace, redact the secret and truncate response bodies."""
    value = str(text or "")
    if secret:
        value = value.replace(secret, "***")
    value = " ".join(value.split())
    return value[:limit]


def api_endpoint(base_url: str, resource: str, *, ensure_v1: bool = True) -> str:
    """Build ``{base_url}[/v1]/{resource}``.

    ``resource`` may already be part of ``base_url`` (a full endpoint URL); in
    that case it is returned unchanged.  Raises :class:`MemoryApiError` for an
    empty/invalid base URL so route handlers can map it to a 4xx/502.
    """
    url = str(base_url or "").strip()
    if not url:
        raise MemoryApiError("未配置上游 base_url", code="configuration_error")
    if not url.lower().startswith(("http://", "https://")):
        raise MemoryApiError(
            "base_url 必须以 http:// 或 https:// 开头", code="configuration_error"
        )
    url = url.rstrip("/")
    resource = resource.lstrip("/")
    lowered = url.lower()
    if lowered.endswith(resource.lower()):
        return url
    if ensure_v1 and not lowered.endswith("/v1"):
        url = f"{url}/v1"
    return f"{url}/{resource}"


def build_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _timeout_seconds(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.1, min(120.0, number))


async def post_json(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    secret: str = "",
    label: str = "上游服务",
) -> dict[str, Any]:
    """POST JSON and normalise HTTP/transport/JSON failures."""
    try:
        async with session.post(url, json=payload, headers=headers) as response:
            status = int(response.status)
            raw = await response.read()
    except asyncio.TimeoutError:
        raise MemoryApiError(
            f"{label}请求超时，请检查 base_url 与网络", code="timeout"
        ) from None
    except aiohttp.ClientError as exc:  # connection refused/DNS/TLS/...
        raise MemoryApiError(
            f"{label}连接失败（{type(exc).__name__}）", code="connection_error"
        ) from None

    text = raw.decode("utf-8", errors="replace")
    if status >= 400:
        detail = sanitize_text(text, secret=secret)
        suffix = f"：{detail}" if detail else ""
        raise MemoryApiError(
            f"{label}返回 HTTP {status}{suffix}", status=status, detail=detail
        )
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        raise MemoryApiError(f"{label}返回了非 JSON 响应") from None
    if not isinstance(parsed, dict):
        raise MemoryApiError(f"{label}返回了非预期响应（不是 JSON 对象）")
    return parsed


def _parse_embedding_payload(payload: dict[str, Any]) -> list[list[float]]:
    items: Any = payload.get("data")
    if not isinstance(items, list):
        items = payload.get("embeddings")
    if not isinstance(items, list) or not items:
        raise MemoryApiError("embedding 响应缺少 data 数组")

    indexed: dict[int, list[float]] = {}
    for position, item in enumerate(items):
        vector: Any
        index = position
        if isinstance(item, (list, tuple)):
            vector = item
        elif isinstance(item, dict):
            vector = item.get("embedding")
            if vector is None:
                vector = item.get("vector")
            try:
                index = int(item.get("index", position))
            except (TypeError, ValueError):
                index = position
        else:
            raise MemoryApiError("embedding 响应中的向量格式不合法")
        if not isinstance(vector, (list, tuple)) or not vector:
            raise MemoryApiError("embedding 响应中的向量为空")
        try:
            indexed[index] = [float(value) for value in vector]
        except (TypeError, ValueError):
            raise MemoryApiError("embedding 响应中的向量包含非数字") from None

    if len(indexed) != len(items):
        raise MemoryApiError("embedding 响应索引不完整")
    try:
        return [indexed[index] for index in range(len(items))]
    except KeyError:
        # Some compatible providers return non-contiguous indexes; keep order.
        return list(indexed.values())


class EmbeddingClient:
    """Async OpenAI-compatible ``/v1/embeddings`` client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str = "",
        dimensions: int = 0,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        try:
            self.dimensions = max(0, int(dimensions or 0))
        except (TypeError, ValueError):
            self.dimensions = 0
        self.timeout_seconds = _timeout_seconds(timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
        try:
            batch = int(batch_size or DEFAULT_BATCH_SIZE)
        except (TypeError, ValueError):
            batch = DEFAULT_BATCH_SIZE
        self.batch_size = max(1, min(MAX_BATCH_SIZE, batch))
        self._session = session
        self._owns_session = session is None

    # -- lifecycle -----------------------------------------------------
    @property
    def endpoint(self) -> str:
        return api_endpoint(self.base_url, "embeddings")

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
            )
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "EmbeddingClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # -- API -----------------------------------------------------------
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` in batches; returns vectors in the input order."""
        cleaned = [str(text if text is not None else "") for text in texts]
        if not cleaned:
            return []
        session = await self._ensure_session()
        vectors: list[list[float]] = []
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            vectors.extend(await self._embed_batch(session, batch))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        if not vectors or not vectors[0]:
            raise MemoryApiError("embedding 响应为空")
        return vectors[0]

    async def _embed_batch(
        self, session: aiohttp.ClientSession, batch: list[str]
    ) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self.model, "input": batch}
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions
        data = await post_json(
            session,
            self.endpoint,
            payload,
            headers=build_headers(self.api_key),
            secret=self.api_key,
            label="Embedding 服务",
        )
        vectors = _parse_embedding_payload(data)
        if len(vectors) != len(batch):
            raise MemoryApiError(
                f"embedding 返回数量不匹配（期望 {len(batch)}，实际 {len(vectors)}）"
            )
        return vectors


__all__ = [
    "EmbeddingClient",
    "MemoryApiError",
    "MASKED_API_KEY",
    "api_endpoint",
    "build_headers",
    "post_json",
    "sanitize_text",
]
