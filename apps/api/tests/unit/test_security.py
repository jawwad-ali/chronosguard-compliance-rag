"""API key scheme + scope hierarchy."""

from chronosguard.core.security import (
    extract_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from chronosguard.core.tenancy import effective_scopes

PEPPER = "test_pepper"


class TestKeyScheme:
    def test_roundtrip_verifies(self) -> None:
        key = generate_api_key("local", pepper=PEPPER)
        assert verify_api_key(key.full_key, key.key_hash, pepper=PEPPER)

    def test_format_is_prefix_dot_secret(self) -> None:
        key = generate_api_key("local", pepper=PEPPER)
        assert key.full_key.startswith("cgk_local_")
        assert key.full_key.split(".")[0] == key.prefix

    def test_tampered_secret_fails(self) -> None:
        key = generate_api_key("local", pepper=PEPPER)
        assert not verify_api_key(key.full_key + "x", key.key_hash, pepper=PEPPER)

    def test_wrong_pepper_fails(self) -> None:
        key = generate_api_key("local", pepper=PEPPER)
        assert not verify_api_key(key.full_key, key.key_hash, pepper="other_pepper")

    def test_hash_is_deterministic_per_pepper(self) -> None:
        assert hash_api_key("abc", pepper=PEPPER) == hash_api_key("abc", pepper=PEPPER)
        assert hash_api_key("abc", pepper=PEPPER) != hash_api_key("abc", pepper="other")

    def test_keys_are_unique(self) -> None:
        keys = {generate_api_key("local", pepper=PEPPER).full_key for _ in range(50)}
        assert len(keys) == 50


class TestPrefixExtraction:
    def test_extracts_valid_prefix(self) -> None:
        assert extract_prefix("cgk_local_ab12cd34.secretpart") == "cgk_local_ab12cd34"

    def test_rejects_missing_dot(self) -> None:
        assert extract_prefix("cgk_local_ab12cd34") is None

    def test_rejects_empty_secret(self) -> None:
        assert extract_prefix("cgk_local_ab12cd34.") is None

    def test_rejects_foreign_namespace(self) -> None:
        assert extract_prefix("sk_live_abc.def") is None


class TestScopeHierarchy:
    def test_admin_implies_everything(self) -> None:
        assert effective_scopes(["admin"]) == frozenset({"admin", "audit", "read"})

    def test_audit_implies_read_not_admin(self) -> None:
        scopes = effective_scopes(["audit"])
        assert scopes == frozenset({"audit", "read"})

    def test_read_is_just_read(self) -> None:
        assert effective_scopes(["read"]) == frozenset({"read"})

    def test_unknown_scopes_are_dropped(self) -> None:
        assert effective_scopes(["superuser", "root"]) == frozenset()
