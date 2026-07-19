from typing import List, Optional

from pydantic import BaseModel, Field


class WatchlistCreate(BaseModel):
    ticker: str
    notes: Optional[str] = None


class AnalysisRunRequest(BaseModel):
    tickers: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    analysis_model: Optional[str] = None
    research_model: Optional[str] = None
    analysis_interval: Optional[int] = None
    openrouter_api_key: Optional[str] = Field(
        default=None,
        description="OpenRouter API key. Leave blank to keep the existing key.",
    )


class ReportGenerateResponse(BaseModel):
    task_id: str
    status: str  # "pending"


class ReportTaskStatus(BaseModel):
    task_id: str
    status: str  # "pending" | "running" | "done" | "failed"
    ticker: str
    report_type: str
    report_id: Optional[int] = None
    rating: Optional[str] = None
    score: Optional[int] = None
    error: Optional[str] = None


class SyncDataRequest(BaseModel):
    tickers: Optional[List[str]] = None
