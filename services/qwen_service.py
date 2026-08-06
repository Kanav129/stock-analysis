"""Qwen / DashScope account status (balance + connectivity)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from utils.logger import logger

DEFAULT_INTL_ORIGIN = "https://dashscope-intl.aliyuncs.com"
DEFAULT_CN_ORIGIN = "https://dashscope.aliyuncs.com"
BALANCE_PATH = "/api/v1/recharge/recharge-balance/query"


class QwenService:
    def __init__(self, api_key: str | None = None) -> None:
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            from config.llm_config import resolve_llm_api_key

            self.api_key = (resolve_llm_api_key() or "").strip()

    def get_status(self) -> dict[str, Any]:
        if not self.api_key:
            return {
                "connected": False,
                "provider": "qwen",
                "message": (
                    "No Qwen API key configured. Add one below or set "
                    "QWEN_API_KEY (or DASHSCOPE_API_KEY) in .env."
                ),
            }

        auth_info = self._verify_auth()
        balance_info = self._get_balance()

        if not auth_info.get("ok"):
            return {
                "connected": False,
                "provider": "qwen",
                "message": auth_info.get("error") or "Failed to authenticate with Qwen / DashScope.",
                "key": None,
                "credits": balance_info.get("data") if balance_info.get("ok") else None,
                "credits_note": None if balance_info.get("ok") else balance_info.get("error"),
            }

        remaining = None
        if balance_info.get("ok"):
            remaining = (balance_info.get("data") or {}).get("remaining")

        low = remaining is not None and float(remaining) < 5.0
        msg = "Connected to Qwen (DashScope)."
        if low:
            msg = "Connected — Qwen balance is low. Top up at qwencloud.com."

        return {
            "connected": True,
            "provider": "qwen",
            "message": msg,
            "low_balance": low,
            "key": auth_info.get("data"),
            "credits": balance_info.get("data") if balance_info.get("ok") else None,
            "credits_note": None
            if balance_info.get("ok")
            else balance_info.get("error"),
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _api_origins(self) -> list[str]:
        """Prefer the region implied by OPENAI_BASE_URL, then try intl + cn."""
        from config.llm_config import resolve_llm_base_url

        base = resolve_llm_base_url()
        origins: list[str] = []
        if base:
            parsed = urlparse(base)
            if parsed.scheme and parsed.netloc:
                origins.append(f"{parsed.scheme}://{parsed.netloc}")
        for origin in (DEFAULT_INTL_ORIGIN, DEFAULT_CN_ORIGIN):
            if origin not in origins:
                origins.append(origin)
        return origins

    def _verify_auth(self) -> dict[str, Any]:
        """Lightweight auth check via the compatible-mode models endpoint."""
        last_error = "Unable to reach Qwen API."
        for origin in self._api_origins():
            url = f"{origin}/compatible-mode/v1/models"
            try:
                res = requests.get(url, headers=self._headers(), timeout=15)
                if res.status_code == 401:
                    return {"ok": False, "error": "Invalid Qwen API key."}
                if res.status_code >= 400:
                    last_error = f"Qwen auth check failed ({res.status_code})."
                    continue
                body = res.json()
                model_count = len(body.get("data") or [])
                return {
                    "ok": True,
                    "data": {
                        "label": "DashScope API key",
                        "models_available": model_count,
                    },
                }
            except Exception as exc:
                logger.warning(f"Qwen models check failed for {origin}: {exc}")
                last_error = str(exc)
        return {"ok": False, "error": last_error}

    def _get_balance(self) -> dict[str, Any]:
        last_error = "View balance and usage in the QwenCloud console (no public balance API for this key type)."
        for origin in self._api_origins():
            url = f"{origin}{BALANCE_PATH}"
            try:
                res = requests.get(url, headers=self._headers(), timeout=15)
                if res.status_code == 401:
                    return {"ok": False, "error": "Invalid Qwen API key."}
                if res.status_code >= 400:
                    last_error = f"Balance query failed ({res.status_code})."
                    continue
                body = res.json()
                remaining = _extract_balance(body)
                if remaining is None:
                    last_error = "Balance response did not include a numeric balance."
                    continue
                return {
                    "ok": True,
                    "data": {
                        "remaining": remaining,
                        "raw": body.get("data") or body.get("output") or body,
                    },
                }
            except Exception as exc:
                logger.warning(f"Qwen balance check failed for {origin}: {exc}")
                last_error = str(exc)
        return {"ok": False, "error": last_error}


def _extract_balance(body: dict[str, Any]) -> float | None:
    """Parse DashScope recharge-balance payloads (shape varies by region/account)."""
    candidates: list[Any] = []
    data = body.get("data")
    output = body.get("output")
    if isinstance(data, dict):
        candidates.extend(
            data.get(k)
            for k in (
                "available_balance",
                "balance",
                "remain_balance",
                "remaining_balance",
                "available_amount",
                "amount",
            )
        )
        nested = data.get("balance_info")
        if isinstance(nested, dict):
            candidates.extend(nested.values())
    if isinstance(output, dict):
        candidates.extend(output.values())

    for value in candidates:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
