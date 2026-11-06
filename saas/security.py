"""Small security helpers shared by auth / invites / sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string

_INVITE_ALPHABET = string.ascii_uppercase + string.digits  # no lowercase/ambiguous


def random_token(nbytes: int = 32) -> str:
    """URL-safe random token (used for session cookies / CSRF)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode()


def random_id(prefix: str, nbytes: int = 12) -> str:
    return f"{prefix}_{secrets.token_hex(nbytes)}"


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def hmac_hex(secret: bytes, message: str) -> str:
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_invite_code() -> str:
    """Human-friendly one-time invite code, e.g. ``INV-7K3M-9Q2X``."""
    raw = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))
    return f"INV-{raw[:4]}-{raw[4:]}"


def normalize_invite_code(code: str) -> str:
    return "".join(code.split()).upper()


def new_otp(digits: int = 6) -> str:
    """Numeric OTP, zero-padded, cryptographically random."""
    upper = 10**digits
    return str(secrets.randbelow(upper)).zfill(digits)
