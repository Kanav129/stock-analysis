from fastapi import APIRouter, HTTPException, Query

from rest_api.schemas import SettingsUpdate
from services.llm_usage_service import LlmUsageService
from services.qwen_service import QwenService
from services.settings_service import SettingsService

router = APIRouter()
settings_service = SettingsService()


@router.get("/settings")
def get_settings():
    return settings_service.get_all()


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    try:
        return settings_service.update(body.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/settings/llm")
def llm_status():
    """Qwen / DashScope connection, balance, and configured models."""
    try:
        status = QwenService().get_status()
        status["analysis_model"] = settings_service.get_raw("analysis_model")
        status["research_model"] = settings_service.get_raw("research_model")
        return status
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/settings/llm/usage")
def llm_usage(range: str = Query("week", pattern="^(week|month)$")):
    """Local LLM spend/token aggregates (today, week, month) + daily series."""
    try:
        return LlmUsageService().get_usage_summary(range_=range)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/settings/openrouter")
def openrouter_status():
    """Deprecated alias — returns Qwen provider status."""
    return llm_status()
