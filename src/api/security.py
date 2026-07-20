"""Authentication context and signed access tokens for the web API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import HTTPException


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


LOCAL_PRINCIPAL = Principal(user_id=0, username="local", role="admin")
_principal_context: ContextVar[Principal] = ContextVar(
    "superclaw_principal",
    default=LOCAL_PRINCIPAL,
)


def auth_required() -> bool:
    return os.environ.get("SUPERCLAW_AUTH_REQUIRED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def current_principal() -> Principal:
    return _principal_context.get()


def set_current_principal(principal: Principal) -> Token:
    return _principal_context.set(principal)


def reset_current_principal(token: Token) -> None:
    _principal_context.reset(token)


def require_principal() -> Principal:
    return current_principal()


def require_admin() -> Principal:
    principal = current_principal()
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return principal


def _secret() -> bytes:
    value = os.environ.get("SUPERCLAW_AUTH_SECRET", "").strip()
    if not value:
        value = "local-development-only-secret"
    return value.encode("utf-8")


def validate_security_config() -> None:
    if not auth_required():
        return
    configured = os.environ.get("SUPERCLAW_AUTH_SECRET", "").strip()
    if len(configured) < 32:
        raise RuntimeError(
            "SUPERCLAW_AUTH_SECRET must contain at least 32 characters when authentication is required"
        )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(
    user_id: int,
    username: str,
    role: str,
    expires_in: Optional[int] = None,
) -> str:
    lifetime = expires_in or int(os.environ.get("SUPERCLAW_AUTH_TOKEN_TTL", "43200"))
    now = int(time.time())
    payload = {
        "uid": int(user_id),
        "sub": str(username),
        "role": str(role or "user"),
        "iat": now,
        "exp": now + max(300, lifetime),
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def decode_access_token(token: str) -> Principal:
    try:
        encoded, signature = token.split(".", 1)
        expected = _encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload: Dict[str, Any] = json.loads(_decode(encoded).decode("utf-8"))
        if int(payload.get("exp") or 0) <= int(time.time()):
            raise ValueError("expired")
        user_id = int(payload.get("uid") or 0)
        username = str(payload.get("sub") or "").strip()
        if user_id <= 0 or not username:
            raise ValueError("invalid subject")
        return Principal(user_id=user_id, username=username, role=str(payload.get("role") or "user"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc


def principal_from_authorization(value: str) -> Optional[Principal]:
    scheme, _, token = str(value or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return decode_access_token(token.strip())
