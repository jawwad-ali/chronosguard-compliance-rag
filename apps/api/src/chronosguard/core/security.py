"""API key scheme: ``cgk_{env}_{prefix8}.{secret32}``.

Stored: plaintext ``prefix`` (indexed, O(1) lookup) + SHA-256(full_key + pepper).
SHA-256 (not argon2/bcrypt) is correct here: keys are high-entropy random
tokens, not human passwords — a slow KDF would only add request latency.
The plaintext is shown exactly once at issuance.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from chronosguard.core.config import get_settings

KEY_NAMESPACE = "cgk"
_PREFIX_HEX_CHARS = 8
_SECRET_BYTES = 32


@dataclass(frozen=True)
class GeneratedKey:
    full_key: str  # show once, never persist
    prefix: str  # store + index
    key_hash: str  # store


def hash_api_key(full_key: str, *, pepper: str | None = None) -> str:
    pepper = pepper if pepper is not None else get_settings().api_key_pepper
    return hashlib.sha256(f"{full_key}{pepper}".encode()).hexdigest()


def generate_api_key(env: str, *, pepper: str | None = None) -> GeneratedKey:
    prefix = f"{KEY_NAMESPACE}_{env}_{secrets.token_hex(_PREFIX_HEX_CHARS // 2)}"
    full_key = f"{prefix}.{secrets.token_urlsafe(_SECRET_BYTES)}"
    return GeneratedKey(
        full_key=full_key, prefix=prefix, key_hash=hash_api_key(full_key, pepper=pepper)
    )


def extract_prefix(presented_key: str) -> str | None:
    """The indexed lookup component, or None for a malformed key."""
    prefix, sep, secret = presented_key.partition(".")
    if not sep or not secret or not prefix.startswith(f"{KEY_NAMESPACE}_"):
        return None
    return prefix


def verify_api_key(presented_key: str, stored_hash: str, *, pepper: str | None = None) -> bool:
    return hmac.compare_digest(hash_api_key(presented_key, pepper=pepper), stored_hash)
