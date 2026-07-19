from fastapi import APIRouter, HTTPException

from rest_api.schemas import SettingsUpdate
from services.openrouter_service import OpenRouterService
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


@router.get("/settings/openrouter")
def openrouter_status():
    """OpenRouter connection, remaining credits (if available), and key usage."""
    try:
        return OpenRouterService().get_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
