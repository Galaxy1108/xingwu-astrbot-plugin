"""Envelope encryption for the SaaS plugin.

Key hierarchy (see handoff doc §6.3)::

    Root KEK (32B, outside the DB, 0400 file or env)
      └─ wrap → Tenant Key (per user, tenant_keys table, AAD tenant:{id}:v1)
            ├─ HKDF(salt=bot_id, info=bot/content/v1) → conversation key
            ├─ HKDF(salt=bot_id, info=bot/memory/v1)  → SQLCipher key
            └─ HKDF(salt=bot_id, info=bot/export/v1)  → export key

Ciphertext envelope: ``ENC1.<key_version>.<base64url(nonce||ct||tag)>``.
Failure is always fail-closed: never return empty plaintext on decrypt errors.
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

ENVELOPE_PREFIX: Final = "ENC1"
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32


class CryptoError(Exception):
    """Raised when a key is unavailable or a ciphertext cannot be opened."""


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _hkdf(ikm: bytes, *, salt: bytes, info: str, length: int = KEY_BYTES) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=salt, info=info.encode()
    ).derive(ikm)


@dataclass
class KeyManager:
    """Loads/creates the root KEK and wraps tenant keys with it."""

    kek_file: Path
    _kek: bytes | None = None

    def __post_init__(self) -> None:
        self.kek_file = Path(self.kek_file)

    # -- root KEK ------------------------------------------------------
    def load_kek(self) -> bytes:
        if self._kek is not None:
            return self._kek
        env = os.environ.get("SAAS_KEK", "").strip()
        if env:
            try:
                raw = bytes.fromhex(env) if len(env) == 64 else b64u_decode(env)
            except Exception as exc:  # noqa: BLE001
                raise CryptoError("SAAS_KEK 格式无效（需要 32 字节 hex/base64url）") from exc
            if len(raw) != KEY_BYTES:
                raise CryptoError("SAAS_KEK 长度必须为 32 字节")
            self._kek = raw
            return raw
        path = self.kek_file
        if path.exists():
            raw = path.read_bytes()
            if len(raw) != KEY_BYTES:
                raise CryptoError("root KEK 文件损坏（长度不是 32 字节）")
        else:
            raw = secrets.token_bytes(KEY_BYTES)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(raw)
            os.chmod(tmp, 0o400)
            os.replace(tmp, path)
            os.chmod(path, 0o400)
            logger.warning(
                "已生成新的 root KEK：%s（请离线备份；丢失将无法解密任何数据）", path
            )
        self._kek = raw
        return raw

    def derive_secret(self, info: str, length: int = KEY_BYTES) -> bytes:
        """Server-side secret derived from the KEK (OTP/invite pepper, etc.)."""
        return _hkdf(self.load_kek(), salt=b"saas/secret/v1", info=info, length=length)

    # -- generic wrapped blobs (platform settings etc.) ----------------
    def wrap(self, plaintext: bytes, *, aad: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self.load_kek()).encrypt(nonce, plaintext, aad)
        return nonce + sealed

    def unwrap(self, blob: bytes, *, aad: bytes) -> bytes:
        if len(blob) <= NONCE_BYTES:
            raise CryptoError("密文损坏")
        nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            return AESGCM(self.load_kek()).decrypt(nonce, sealed, aad)
        except InvalidTag as exc:
            raise CryptoError("解封失败（KEK 不匹配或数据损坏）") from exc

    # -- tenant key wrapping -------------------------------------------
    def _wrap_aad(self, tenant_id: str, key_version: int) -> bytes:
        return f"tenant:{tenant_id}:v{key_version}".encode()

    def wrap_tenant_key(self, tenant_id: str, key: bytes, key_version: int = 1) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self.load_kek()).encrypt(
            nonce, key, self._wrap_aad(tenant_id, key_version)
        )
        return nonce + sealed

    def unwrap_tenant_key(
        self, tenant_id: str, blob: bytes, key_version: int = 1
    ) -> bytes:
        if len(blob) <= NONCE_BYTES:
            raise CryptoError("租户密钥密文损坏")
        nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            return AESGCM(self.load_kek()).decrypt(
                nonce, sealed, self._wrap_aad(tenant_id, key_version)
            )
        except InvalidTag as exc:
            raise CryptoError("租户密钥解封失败（KEK 不匹配或数据损坏）") from exc


class TenantCipher:
    """AES-256-GCM envelope operations for one tenant."""

    def __init__(self, tenant_key: bytes, tenant_id: str) -> None:
        if len(tenant_key) != KEY_BYTES:
            raise CryptoError("租户密钥长度必须为 32 字节")
        self._tenant_key = tenant_key
        self._tenant_id = tenant_id

    def subkey(self, bot_id: str, purpose: str, *, key_version: int = 1) -> bytes:
        return _hkdf(
            self._tenant_key,
            salt=bot_id.encode(),
            info=f"bot/{purpose}/v{key_version}",
        )

    def _aad(
        self,
        *,
        bot_id: str,
        purpose: str,
        record_id: str,
        key_version: int,
    ) -> bytes:
        return (
            f"{self._tenant_id}|{bot_id}|{purpose}|{record_id}|v{key_version}".encode()
        )

    def encrypt_text(
        self,
        plaintext: str,
        *,
        bot_id: str,
        purpose: str,
        record_id: str = "",
        key_version: int = 1,
    ) -> str:
        key = self.subkey(bot_id, purpose, key_version=key_version)
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(key).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            self._aad(
                bot_id=bot_id,
                purpose=purpose,
                record_id=record_id,
                key_version=key_version,
            ),
        )
        return f"{ENVELOPE_PREFIX}.{key_version}.{b64u_encode(nonce + sealed)}"

    def decrypt_text(
        self,
        token: str,
        *,
        bot_id: str,
        purpose: str,
        record_id: str = "",
    ) -> str:
        try:
            prefix, version_raw, body = token.split(".", 2)
            if prefix != ENVELOPE_PREFIX:
                raise CryptoError("未知的密文信封格式")
            key_version = int(version_raw)
            raw = b64u_decode(body)
            nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
            key = self.subkey(bot_id, purpose, key_version=key_version)
            plaintext = AESGCM(key).decrypt(
                nonce,
                sealed,
                self._aad(
                    bot_id=bot_id,
                    purpose=purpose,
                    record_id=record_id,
                    key_version=key_version,
                ),
            )
            return plaintext.decode("utf-8")
        except CryptoError:
            raise
        except InvalidTag as exc:
            raise CryptoError("密文认证失败（数据被篡改或密钥不匹配）") from exc
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(f"密码文解析失败：{exc}") from exc

    def encrypt_bytes(
        self,
        payload: bytes,
        *,
        bot_id: str,
        purpose: str,
        record_id: str = "",
        key_version: int = 1,
    ) -> bytes:
        key = self.subkey(bot_id, purpose, key_version=key_version)
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(key).encrypt(
            nonce,
            payload,
            self._aad(
                bot_id=bot_id,
                purpose=purpose,
                record_id=record_id,
                key_version=key_version,
            ),
        )
        return nonce + sealed

    def decrypt_bytes(
        self, payload: bytes, *, bot_id: str, purpose: str, record_id: str = ""
    ) -> bytes:
        nonce, sealed = payload[:NONCE_BYTES], payload[NONCE_BYTES:]
        last_error: Exception | None = None
        for version in range(1, 11):
            key = self.subkey(bot_id, purpose, key_version=version)
            try:
                return AESGCM(key).decrypt(
                    nonce,
                    sealed,
                    self._aad(
                        bot_id=bot_id,
                        purpose=purpose,
                        record_id=record_id,
                        key_version=version,
                    ),
                )
            except InvalidTag as exc:
                last_error = exc
                continue
        raise CryptoError("二进制密文认证失败") from last_error


def constant_time_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
