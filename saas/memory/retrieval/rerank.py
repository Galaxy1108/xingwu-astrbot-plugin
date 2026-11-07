"""Cohere / Jina compatible ``/v1/rerank`` client (aiohttp).

Both providers expose the same wire shape::

    POST {base_url}/v1/rerank
    {"model": ..., "query": ..., "documents": [...], "top_n": N}
    -> {"results": [{"index": 0, "relevance_score": 0.93}, ...]}

Some compatible gateways instead answer::

    -> {"data": [{"index": 0, "score": 0.93}, ...]}

:func:`parse_rerank_payload` accepts either shape.  Transport/HTTP problems
are normalised to :class:`~.embedding.MemoryApiError` (no key leakage).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import aiohttp

from .embedding import MemoryApiError, api_endpoint, build_headers, post_json

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_TOP_N = 10


@dataclass(frozen=True)
class RerankResult:
    """One reranked document: original ``index`` plus relevance ``score``."""

    index: int
    score: float

    def as_dict(self) -> dict[str, float | int]:
        return {"index": self.index, "score": self.score}


def _parse_result_item(
    item: Any, document_count: int
) -> RerankResult | None:
    if not isinstance(item, dict):
        return None
    raw_index = item.get("index")
    if raw_index is None:
        return None
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= document_count:
        return None
    raw_score = item.get("relevance_score")
    if raw_score is None:
        raw_score = item.get("score")
    if raw_score is None:
        return None
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return RerankResult(index=index, score=score)


def _result_items(payload: Any) -> list[Any] | None:
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if isinstance(results, list):
        return results
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "items", "data"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return candidate
    return None


def parse_rerank_payload(
    payload: Any, document_count: int
) -> list[RerankResult]:
    """Parse ``results:[{index,relevance_score}]`` or ``data:[{index,score}]``.

    Returns results sorted by descending score (ties keep the original index
    order).  An empty list is a valid response; a structurally invalid payload
    raises :class:`MemoryApiError`.
    """
    items = _result_items(payload)
    if items is None:
        raise MemoryApiError("rerank 响应缺少 results/data 数组")
    parsed: list[RerankResult] = []
    seen: set[int] = set()
    for item in items:
        result = _parse_result_item(item, document_count)
        if result is None or result.index in seen:
            continue
        seen.add(result.index)
        parsed.append(result)
    parsed.sort(key=lambda result: (-result.score, result.index))
    return parsed


class RerankClient:
    """Async Cohere/Jina-compatible ``/v1/rerank`` client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str = "",
        top_n: int = DEFAULT_TOP_N,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        try:
            self.top_n = max(0, int(top_n or 0))
        except (TypeError, ValueError):
            self.top_n = DEFAULT_TOP_N
        try:
            number = float(timeout_seconds)
        except (TypeError, ValueError):
            number = DEFAULT_TIMEOUT_SECONDS
        self.timeout_seconds = max(0.1, min(120.0, number))
        self._session = session
        self._owns_session = session is None

    # -- lifecycle -----------------------------------------------------
    @property
    def endpoint(self) -> str:
        return api_endpoint(self.base_url, "rerank")

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

    async def __aenter__(self) -> "RerankClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # -- API -----------------------------------------------------------
    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        docs = [str(document if document is not None else "") for document in documents]
        if not docs:
            return []
        session = await self._ensure_session()
        limit = self.top_n if top_n is None else int(top_n)
        payload: dict[str, Any] = {
            "model": self.model,
            "query": str(query or ""),
            "documents": docs,
        }
        if limit > 0:
            payload["top_n"] = min(limit, len(docs))
        data = await post_json(
            session,
            self.endpoint,
            payload,
            headers=build_headers(self.api_key),
            secret=self.api_key,
            label="Rerank 服务",
        )
        return parse_rerank_payload(data, len(docs))


__all__ = ["RerankClient", "RerankResult", "parse_rerank_payload"]
