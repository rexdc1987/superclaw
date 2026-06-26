"""Token Manager 模块单元测试。"""
import json
import time
import pytest
import tempfile
from pathlib import Path

from rpa.auth.token_manager import TokenInfo, TokenStore, TokenManager


# ============================================================
# TokenInfo 测试
# ============================================================

class TestTokenInfo:
    def test_is_expired(self):
        token = TokenInfo(access_token="abc", expires_at=time.time() - 10)
        assert token.is_expired is True

    def test_is_not_expired(self):
        token = TokenInfo(access_token="abc", expires_at=time.time() + 3600)
        assert token.is_expired is False

    def test_remaining_seconds(self):
        future = time.time() + 100
        token = TokenInfo(access_token="abc", expires_at=future)
        assert 95 <= token.remaining_seconds <= 105

    def test_authorization_header(self):
        token = TokenInfo(access_token="mytoken", token_type="Bearer")
        assert token.authorization == "Bearer mytoken"

    def test_to_dict_and_back(self):
        token = TokenInfo(access_token="abc", refresh_token="xyz", expires_at=12345)
        d = token.to_dict()
        token2 = TokenInfo.from_dict(d)
        assert token2.access_token == "abc"
        assert token2.refresh_token == "xyz"


# ============================================================
# TokenStore 测试
# ============================================================

class TestTokenStore:
    def test_save_and_load(self, tmp_path):
        store = TokenStore(str(tmp_path))
        token = TokenInfo(access_token="abc123", refresh_token="xyz789", expires_at=99999)
        store.save("test_account", token)

        loaded = store.load("test_account")
        assert loaded is not None
        assert loaded.access_token == "abc123"

    def test_load_nonexistent(self, tmp_path):
        store = TokenStore(str(tmp_path))
        assert store.load("nonexistent") is None

    def test_delete(self, tmp_path):
        store = TokenStore(str(tmp_path))
        token = TokenInfo(access_token="abc", expires_at=99999)
        store.save("test", token)
        assert store.delete("test") is True
        assert store.load("test") is None

    def test_list_accounts(self, tmp_path):
        store = TokenStore(str(tmp_path))
        store.save("acc1", TokenInfo(access_token="a", expires_at=99999))
        store.save("acc2", TokenInfo(access_token="b", expires_at=99999))
        accounts = store.list_accounts()
        assert "acc1" in accounts
        assert "acc2" in accounts

    def test_encoded_tokens(self, tmp_path):
        store = TokenStore(str(tmp_path), encode_tokens=True)
        token = TokenInfo(access_token="super_secret_token", expires_at=99999)
        store.save("encoded", token)

        # Raw file should not contain plaintext token
        raw = json.loads((tmp_path / "encoded.json").read_text())
        assert raw["access_token"] != "super_secret_token"

        # Loaded should be decoded
        loaded = store.load("encoded")
        assert loaded.access_token == "super_secret_token"

    def test_clear(self, tmp_path):
        store = TokenStore(str(tmp_path))
        store.save("a", TokenInfo(access_token="a", expires_at=99999))
        store.save("b", TokenInfo(access_token="b", expires_at=99999))
        count = store.clear()
        assert count == 2
        assert store.list_accounts() == []


# ============================================================
# TokenManager 测试
# ============================================================

class TestTokenManager:
    def test_save_and_get(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        token = TokenInfo(access_token="abc", expires_at=time.time() + 3600)
        tm.save("user1", token)

        got = tm.get("user1")
        assert got is not None
        assert got.access_token == "abc"

    def test_get_valid(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        expired = TokenInfo(access_token="old", expires_at=time.time() - 100)
        tm.save("expired_user", expired)
        assert tm.get_valid("expired_user") is None

        valid = TokenInfo(access_token="new", expires_at=time.time() + 3600)
        tm.save("valid_user", valid)
        assert tm.get_valid("valid_user") is not None

    def test_auth_headers(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        tm.save("h", TokenInfo(access_token="tok123", token_type="Bearer", expires_at=99999))
        headers = tm.auth_headers("h")
        assert headers["Authorization"] == "Bearer tok123"

    def test_auth_headers_missing(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        assert tm.auth_headers("nonexistent") == {}

    def test_delete(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        tm.save("del_me", TokenInfo(access_token="x", expires_at=99999))
        assert tm.delete("del_me") is True
        assert tm.get("del_me") is None

    def test_stats(self, tmp_path):
        tm = TokenManager(storage_dir=str(tmp_path))
        tm.save("a", TokenInfo(access_token="a", expires_at=time.time() + 3600))
        tm.save("b", TokenInfo(access_token="b", expires_at=time.time() - 100))
        stats = tm.stats()
        assert stats["total_accounts"] == 2
        assert stats["valid_tokens"] == 1
        assert stats["expired_tokens"] == 1

    def test_persistence_across_instances(self, tmp_path):
        tm1 = TokenManager(storage_dir=str(tmp_path))
        tm1.save("persist", TokenInfo(access_token="persist_tok", expires_at=99999))

        # New instance loads from disk
        tm2 = TokenManager(storage_dir=str(tmp_path))
        assert tm2.get("persist") is not None
        assert tm2.get("persist").access_token == "persist_tok"
