"""Password hashing: PBKDF2-HMAC-SHA256, 210k iterations, 16-byte salt.

Storage format (self-describing, versioned)::

    pbkdf2_sha256$210000$<salt_b64>$<hash_b64>

* ``salt_b64`` / ``hash_b64`` are URL-safe base64 without padding.
* Verification uses :func:`hmac.compare_digest` (constant time).
* :func:`needs_rehash` lets ``AuthService`` transparently upgrade a weak/old
  hash after a successful login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=32
    )


def known_iterations(encoded: str) -> int | None:
    """Return the iteration count of a stored hash, or ``None`` if malformed."""
    if not encoded:
        return None
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return None
    try:
        iterations = int(parts[1])
    except (TypeError, ValueError):
        return None
    if iterations <= 0:
        return None
    return iterations


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a plaintext password into the self-describing storage format."""
    if password is None:
        raise ValueError("password is required")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(str(password), salt, int(iterations))
    return f"{ALGORITHM}${int(iterations)}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification; malformed hashes verify as ``False``."""
    if not encoded or not password:
        return False
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return False
    try:
        iterations = int(parts[1])
        salt = _b64decode(parts[2])
        expected = _b64decode(parts[3])
    except (TypeError, ValueError):
        return False
    if iterations <= 0 or not salt or not expected:
        return False
    actual = _derive(str(password), salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(encoded: str) -> bool:
    """True when the stored hash should be replaced after a successful login."""
    iterations = known_iterations(encoded)
    if iterations is None:
        return True
    return iterations != PBKDF2_ITERATIONS


__all__ = [
    "ALGORITHM",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PBKDF2_ITERATIONS",
    "SALT_BYTES",
    "hash_password",
    "known_iterations",
    "needs_rehash",
    "verify_password",
]
