"""Admin-key + guest-token auth. When ADMIN_KEY is unset, the API stays open."""

from __future__ import annotations

import json
import os
import secrets
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

load_dotenv()

GUEST_TOKEN = "__desk_guest__"

PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/auth/login",
    "/auth/guest",
    "/auth/status",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
})

GUEST_ALLOWED_WRITES = frozenset({
    ("POST", "/stock/prices/live-refresh"),
})

router = APIRouter(prefix="/auth", tags=["Auth"])


def _admin_key() -> str:
    return (os.getenv("ADMIN_KEY") or "").strip()


def auth_required() -> bool:
    return bool(_admin_key())


def key_matches(provided: str | None) -> bool:
    expected = _admin_key()
    if not expected:
        return True
    if not provided:
        return False
    # compare_digest requires equal-length strings
    if len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def guest_key_matches(provided: str | None) -> bool:
    if not provided:
        return False
    if len(provided) != len(GUEST_TOKEN):
        return False
    return secrets.compare_digest(provided, GUEST_TOKEN)


def get_auth_role(request: Any) -> str:
    return getattr(request.state, "auth_role", "admin")


def _normalize_path(path: str) -> str:
    # Collapse duplicate slashes and trailing slash
    cleaned = "/" + "/".join(p for p in path.split("/") if p)
    return cleaned or "/"


def _canonical_path(path: str) -> str:
    normalized = _normalize_path(path)
    if normalized.startswith("/api/"):
        return _normalize_path(normalized[4:])
    return normalized


def _is_public_path(path: str) -> bool:
    normalized = _canonical_path(path)
    if normalized in PUBLIC_PATHS:
        return True
    if normalized.startswith("/docs") or normalized.startswith("/redoc"):
        return True
    return False


def _is_settings_path(path: str) -> bool:
    normalized = _canonical_path(path)
    return normalized == "/settings" or normalized.startswith("/settings/")


def _is_guest_allowed_write(method: str, path: str) -> bool:
    return (method.upper(), _canonical_path(path)) in GUEST_ALLOWED_WRITES


def _set_role(scope: Scope, role: str) -> None:
    state = scope.setdefault("state", {})
    state["auth_role"] = role


async def _send_error(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("latin-1")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class LoginBody(BaseModel):
    key: str = Field(..., min_length=1)


@router.get("/status")
def status():
    return {"auth_required": auth_required()}


@router.post("/login")
def login(body: LoginBody):
    if not auth_required():
        return {"ok": True, "auth_required": False, "role": "admin"}
    if not key_matches(body.key.strip()):
        raise HTTPException(status_code=401, detail="Invalid access key")
    return {"ok": True, "auth_required": True, "role": "admin"}


@router.post("/guest")
def guest_login():
    return {
        "ok": True,
        "auth_required": auth_required(),
        "role": "guest",
        "token": GUEST_TOKEN,
    }


class AdminKeyMiddleware:
    """Pure ASGI middleware — avoids BaseHTTPMiddleware eating POST bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not auth_required():
            _set_role(scope, "admin")
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or "/"
        if _is_public_path(path):
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if key_matches(token):
            _set_role(scope, "admin")
            await self.app(scope, receive, send)
            return

        if guest_key_matches(token):
            method_u = str(method).upper()
            if method_u in ("GET", "HEAD") and _is_settings_path(path):
                await _send_error(send, 403, "Forbidden")
                return
            if method_u not in ("GET", "HEAD") and not _is_guest_allowed_write(method_u, path):
                await _send_error(send, 403, "Forbidden")
                return
            _set_role(scope, "guest")
            await self.app(scope, receive, send)
            return

        await _send_error(send, 401, "Unauthorized")
