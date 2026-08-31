import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.security import (
    Principal,
    decode_access_token,
    issue_access_token,
    reset_current_principal,
    set_current_principal,
)
from services.user_service import _hash_password, _verify_password
from services.user_service import UserService


def test_signed_access_token_round_trip(monkeypatch):
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    token = issue_access_token(12, "operator", "user")
    principal = decode_access_token(token)
    assert principal == Principal(user_id=12, username="operator", role="user")


def test_signed_access_token_rejects_tampering(monkeypatch):
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    token = issue_access_token(12, "operator", "user")
    encoded, signature = token.split(".", 1)
    with pytest.raises(HTTPException, match="Invalid or expired"):
        decode_access_token(f"{encoded}x.{signature}")


def test_password_hash_uses_pbkdf2_and_accepts_legacy_hash():
    current = _hash_password("strong-password")
    assert current.startswith("pbkdf2_sha256$")
    assert _verify_password("strong-password", current) is True
    assert _verify_password("wrong", current) is False

    salt = "legacy-salt"
    digest = hashlib.sha256((salt + "old-password").encode()).hexdigest()
    assert _verify_password("old-password", f"{salt}${digest}") is True


def test_owner_filter_scopes_regular_users():
    from rpa.dashboard import routes_hongguo

    token = set_current_principal(Principal(user_id=7, username="user", role="user"))
    try:
        assert routes_hongguo._owner_filter() == ("owner_user_id=%s", [7])
    finally:
        reset_current_principal(token)


def test_owner_filter_allows_admin_global_view():
    from rpa.dashboard import routes_hongguo

    token = set_current_principal(Principal(user_id=1, username="admin", role="admin"))
    try:
        assert routes_hongguo._owner_filter() == ("", [])
    finally:
        reset_current_principal(token)


def test_authentication_middleware_rejects_missing_token(monkeypatch):
    import api.main as main_module

    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    monkeypatch.setattr(main_module, "reconcile_runtime_state", lambda: {})
    with TestClient(main_module.app) as client:
        response = client.get("/api/v1/hongguo/tasks")
    assert response.status_code == 401


def test_authentication_middleware_rejects_token_for_missing_user(monkeypatch):
    import api.main as main_module

    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "reconcile_runtime_state", lambda: {})
    token = issue_access_token(999999, "missing-user", "admin")
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "登录账号不存在"


def test_local_login_returns_real_signed_token(monkeypatch):
    import api.main as main_module

    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    monkeypatch.setattr(main_module, "reconcile_runtime_state", lambda: {})
    with TestClient(main_module.app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "tester", "password": "anything"},
        )
    assert response.status_code == 200
    data = response.json()
    assert decode_access_token(data["access_token"]).username == "tester"


def test_regular_user_cannot_change_global_settings(monkeypatch):
    import api.main as main_module

    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SUPERCLAW_AUTH_SECRET", "x" * 40)
    monkeypatch.setattr(main_module, "reconcile_runtime_state", lambda: {})
    user = UserService().create_user("regular", "password-123", role="user")
    token = issue_access_token(user.id, user.username, user.role, user.auth_version)
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/settings/ai",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


def test_password_change_invalidates_existing_token():
    service = UserService()
    user = service.create_user("operator", "old-password", role="user")
    old_principal = Principal(
        user_id=user.id,
        username=user.username,
        role=user.role,
        auth_version=user.auth_version,
    )

    service.change_password(user.id, "old-password", "new-password")

    with pytest.raises(ValueError, match="登录状态已失效"):
        service.validate_principal(old_principal)


def test_disabled_user_is_rejected_immediately():
    service = UserService()
    user = service.create_user("disabled-user", "password-123", role="user")
    principal = Principal(user.id, user.username, user.role, user.auth_version)

    service.update_user(user.id, status="disabled")

    with pytest.raises(ValueError, match="已禁用"):
        service.validate_principal(principal)


def test_last_active_admin_cannot_be_disabled_or_deleted():
    service = UserService()
    admin = service.create_user("admin", "password-123", role="admin")

    with pytest.raises(ValueError, match="至少一个可用管理员"):
        service.update_user(admin.id, status="disabled")
    with pytest.raises(ValueError, match="至少一个可用管理员"):
        service.delete_user(admin.id)


def test_admin_cannot_disable_own_account():
    service = UserService()
    first = service.create_user("admin-one", "password-123", role="admin")
    service.create_user("admin-two", "password-123", role="admin")

    with pytest.raises(ValueError, match="不能禁用当前登录账号"):
        service.update_user(first.id, actor_user_id=first.id, status="disabled")


def test_screenshot_proxy_rejects_paths_outside_root(tmp_path, monkeypatch):
    import api.main as main_module
    from rpa.dashboard import routes_hongguo

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"not-an-image")
    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SUPERCLAW_SCREENSHOT_ROOT", str(allowed))
    monkeypatch.setattr(main_module, "reconcile_runtime_state", lambda: {})
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/hongguo/tasks/screenshot/proxy",
            params={"path": str(outside)},
        )
    assert response.status_code == 403
