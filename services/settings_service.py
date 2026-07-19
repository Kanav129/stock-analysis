import os

from db.db_factory import get_db_client

SECRET_KEYS = frozenset({"openrouter_api_key"})


def _mask_secret(value: str) -> str:
    v = value.strip()
    if len(v) <= 10:
        return "••••••••"
    return f"{v[:7]}…{v[-4:]}"


class SettingsService:
    DEFAULTS = {
        "analysis_model": os.getenv("ANALYSIS_MODEL", "deepseek/deepseek-v4-pro"),
        "research_model": os.getenv("RESEARCH_MODEL", "deepseek/deepseek-v4-flash"),
        "analysis_interval": os.getenv("ANALYSIS_INTERVAL", os.getenv("SCRAPING_INTERVAL", "86400")),
    }

    def _stored(self) -> dict[str, str]:
        db = get_db_client()
        try:
            rows, _ = db.fetch_query("SELECT key, value FROM app_settings")
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    def get_raw(self, key: str) -> str | None:
        """Unmasked value for a single key (server-side use only)."""
        stored = self._stored()
        if key in stored and stored[key]:
            return stored[key]
        if key == "openrouter_api_key":
            return os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or None
        if key in self.DEFAULTS:
            return str(self.DEFAULTS[key])
        return None

    def get_all(self) -> dict:
        """Public settings view — secrets are masked, never returned in full."""
        stored = self._stored()
        merged = {**self.DEFAULTS, **{k: v for k, v in stored.items() if k not in SECRET_KEYS}}

        env_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        db_key = stored.get("openrouter_api_key") or ""
        active_key = db_key or env_key
        merged["openrouter_api_key_set"] = "true" if active_key else "false"
        merged["openrouter_api_key_masked"] = _mask_secret(active_key) if active_key else ""
        merged["openrouter_api_key_source"] = (
            "settings" if db_key else ("env" if env_key else "none")
        )
        # Never expose raw secret
        merged.pop("openrouter_api_key", None)
        return merged

    def update(self, data: dict) -> dict:
        db = get_db_client()
        allowed = {
            "analysis_model",
            "research_model",
            "analysis_interval",
            "openrouter_api_key",
        }
        for key, value in data.items():
            if key not in allowed:
                continue
            if key == "openrouter_api_key":
                # Empty / placeholder = leave existing key unchanged
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
                (key, str(value).strip()),
            )
        return self.get_all()

    def get_interval_seconds(self) -> int:
        settings = self.get_all()
        try:
            return int(settings.get("analysis_interval", 86400))
        except (TypeError, ValueError):
            return 86400
