import os

from db.db_factory import get_db_client

SECRET_KEYS = frozenset({"llm_api_key", "openrouter_api_key"})

# Daily sync / weekly analysis defaults (seconds)
DEFAULT_SYNC_INTERVAL = "86400"       # 24h
DEFAULT_ANALYSIS_INTERVAL = "604800"  # 7d

_LLM_API_KEY_ENV_KEYS = (
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)


def _mask_secret(value: str) -> str:
    v = value.strip()
    if len(v) <= 10:
        return "••••••••"
    return f"{v[:7]}…{v[-4:]}"


def _env_llm_api_key() -> str:
    for key in _LLM_API_KEY_ENV_KEYS:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return ""


class SettingsService:
    DEFAULTS = {
        "analysis_model": os.getenv("ANALYSIS_MODEL", "qwen3.7-max"),
        "research_model": os.getenv("RESEARCH_MODEL", "qwen3.7-flash"),
        "sync_interval": os.getenv("SYNC_INTERVAL", DEFAULT_SYNC_INTERVAL),
        "analysis_interval": os.getenv(
            "ANALYSIS_INTERVAL",
            os.getenv("SCRAPING_INTERVAL", DEFAULT_ANALYSIS_INTERVAL),
        ),
    }

    def _stored(self) -> dict[str, str]:
        db = get_db_client()
        try:
            rows, _ = db.fetch_query("SELECT key, value FROM app_settings")
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    def _stored_llm_api_key(self, stored: dict[str, str]) -> str:
        return (stored.get("llm_api_key") or stored.get("openrouter_api_key") or "").strip()

    def get_raw(self, key: str) -> str | None:
        """Unmasked value for a single key (server-side use only)."""
        stored = self._stored()
        if key in stored and stored[key]:
            return stored[key]
        if key == "llm_api_key":
            db_key = self._stored_llm_api_key(stored)
            if db_key:
                return db_key
            env_key = _env_llm_api_key()
            return env_key or None
        if key == "openrouter_api_key":
            return self.get_raw("llm_api_key")
        if key in self.DEFAULTS:
            return str(self.DEFAULTS[key])
        return None

    def get_all(self) -> dict:
        """Public settings view — secrets are masked, never returned in full."""
        stored = self._stored()
        merged = {**self.DEFAULTS, **{k: v for k, v in stored.items() if k not in SECRET_KEYS}}

        env_key = _env_llm_api_key()
        db_key = self._stored_llm_api_key(stored)
        active_key = db_key or env_key
        merged["llm_provider"] = "qwen"
        merged["llm_api_key_set"] = "true" if active_key else "false"
        merged["llm_api_key_masked"] = _mask_secret(active_key) if active_key else ""
        merged["llm_api_key_source"] = (
            "settings" if db_key else ("env" if env_key else "none")
        )
        # Back-compat for older clients
        merged["openrouter_api_key_set"] = merged["llm_api_key_set"]
        merged["openrouter_api_key_masked"] = merged["llm_api_key_masked"]
        merged["openrouter_api_key_source"] = merged["llm_api_key_source"]
        return merged

    def update(self, data: dict) -> dict:
        db = get_db_client()
        allowed = {
            "analysis_model",
            "research_model",
            "sync_interval",
            "analysis_interval",
            "llm_api_key",
            "openrouter_api_key",
        }
        for key, value in data.items():
            if key not in allowed:
                continue
            store_key = "llm_api_key" if key == "openrouter_api_key" else key
            if store_key == "llm_api_key":
                if value is None:
                    continue
                text = str(value).strip()
                if not text or text.startswith("••••") or "…" in text:
                    continue
            db.execute_query(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (store_key, str(value).strip()),
            )
        return self.get_all()

    def get_sync_interval_seconds(self) -> int:
        return self._parse_interval("sync_interval", int(DEFAULT_SYNC_INTERVAL))

    def get_analysis_interval_seconds(self) -> int:
        return self._parse_interval("analysis_interval", int(DEFAULT_ANALYSIS_INTERVAL))

    def get_interval_seconds(self) -> int:
        """Back-compat alias — returns analysis interval."""
        return self.get_analysis_interval_seconds()

    def _parse_interval(self, key: str, default: int) -> int:
        raw = self.get_raw(key)
        try:
            value = int(raw) if raw is not None else default
            return max(60, value)
        except (TypeError, ValueError):
            return default
