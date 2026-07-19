"""Simple admin-key auth. When ADMIN_KEY is unset, the API stays open."""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


class AdminKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not auth_required():
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if key_matches(token):
            return await call_next(request)

        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
