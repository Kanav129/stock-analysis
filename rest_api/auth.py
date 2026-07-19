"""Simple admin-key auth. When ADMIN_KEY is unset, the API stays open."""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

load_dotenv()

PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/auth/login",
    "/auth/status",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
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


class LoginBody(BaseModel):
    key: str = Field(..., min_length=1)


@router.get("/status")
def status():
    return {"auth_required": auth_required()}


@router.post("/login")
def login(body: LoginBody):
    if not auth_required():
        return {"ok": True, "auth_required": False}
    if not key_matches(body.key.strip()):
        raise HTTPException(status_code=401, detail="Invalid access key")
    return {"ok": True, "auth_required": True}


class AdminKeyMiddleware:
    """Pure ASGI middleware — avoids BaseHTTPMiddleware eating POST bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not auth_required():
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "").rstrip("/") or "/"
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
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
            await self.app(scope, receive, send)
            return

        body = b'{"detail":"Unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
