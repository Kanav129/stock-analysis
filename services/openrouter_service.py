"""OpenRouter account / key status (credits + usage)."""
from __future__ import annotations

from typing import Any

import requests

from utils.logger import logger

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterService:
    def __init__(self, api_key: str | None = None) -> None:
        from config.llm_config import resolve_openrouter_api_key

        self.api_key = (api_key or resolve_openrouter_api_key() or "").strip()

    def get_status(self) -> dict[str, Any]:
        if not self.api_key:
            return {
                "connected": False,
                "message": "No OpenRouter API key configured. Add one below or set OPENROUTER_API_KEY in .env.",
            }

        key_info = self._get_key()
        credits_info = self._get_credits()

        if not key_info.get("ok"):
            return {
                "connected": False,
                "message": key_info.get("error") or "Failed to authenticate with OpenRouter.",
                "key": None,
                "credits": credits_info if credits_info.get("ok") else None,
            }

        data = key_info.get("data") or {}
        account_remaining = None
        if credits_info.get("ok"):
            account_remaining = (credits_info.get("data") or {}).get("remaining")
        key_remaining = data.get("limit_remaining")
        check_remaining = (
            account_remaining if account_remaining is not None else key_remaining
        )
        low = check_remaining is not None and float(check_remaining) < 5.0

        msg = "Connected to OpenRouter."
        if low:
            msg = "Connected — credits running low. Top up soon at openrouter.ai/credits."

        return {
            "connected": True,
            "message": msg,
            "low_balance": low,
            "key": {
                "label": data.get("label"),
                "limit": data.get("limit"),
                "limit_remaining": data.get("limit_remaining"),
                "limit_reset": data.get("limit_reset"),
                "usage": data.get("usage"),
                "usage_daily": data.get("usage_daily"),
                "usage_weekly": data.get("usage_weekly"),
                "usage_monthly": data.get("usage_monthly"),
                "is_free_tier": data.get("is_free_tier"),
            },
            "credits": credits_info.get("data") if credits_info.get("ok") else None,
            "credits_note": None
            if credits_info.get("ok")
            else credits_info.get("error"),
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/stocks-insights-ai-agent",
            "X-Title": "Stock Insights AI Agent",
        }

    def _get_key(self) -> dict[str, Any]:
        try:
            res = requests.get(
                f"{OPENROUTER_BASE}/key",
                headers=self._headers(),
                timeout=15,
            )
            if res.status_code == 401:
                return {"ok": False, "error": "Invalid OpenRouter API key."}
            if res.status_code >= 400:
                return {"ok": False, "error": f"OpenRouter key check failed ({res.status_code})."}
            body = res.json()
            return {"ok": True, "data": body.get("data") or body}
        except Exception as exc:
            logger.error(f"OpenRouter /key failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def _get_credits(self) -> dict[str, Any]:
        """Account credits (may require management key — soft-fail if unavailable)."""
        try:
            res = requests.get(
                f"{OPENROUTER_BASE}/credits",
                headers=self._headers(),
                timeout=15,
            )
            if res.status_code >= 400:
                return {
                    "ok": False,
                    "error": "Account credit balance requires a management key; showing per-key usage instead.",
                }
            body = res.json()
            data = body.get("data") or body
            # Typical: { total_credits, total_usage } → remaining = total - usage
            total = data.get("total_credits")
            used = data.get("total_usage")
            remaining = None
            if total is not None and used is not None:
                try:
                    remaining = float(total) - float(used)
                except (TypeError, ValueError):
                    remaining = None
            return {
                "ok": True,
                "data": {
                    "total_credits": total,
                    "total_usage": used,
                    "remaining": remaining,
                },
            }
        except Exception as exc:
            logger.warning(f"OpenRouter /credits unavailable: {exc}")
            return {"ok": False, "error": str(exc)}
