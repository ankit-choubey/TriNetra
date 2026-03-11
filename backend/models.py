"""
Trinetra FastAPI Backend — Pydantic Models
Request/response schemas for all API endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class ApplicationCreate(BaseModel):
    """Form data from Devraj's frontend (14 fields)."""
    company_name: str = ""
    pan: str = ""
    gstin: str = ""
    cin: str = ""
    loan_amount_requested: float = 0
    loan_purpose: str = ""
    industry_sector: str = ""
    # ── Additional applicant fields ──
    promoter_name: Optional[str] = ""
    promoter_din: Optional[str] = ""
    years_in_business: Optional[int] = 0
    annual_turnover: Optional[float] = 0
    existing_bank_loans: Optional[float] = 0
    collateral_offered: Optional[str] = ""
    contact_email: Optional[str] = ""


class ApplicationResponse(BaseModel):
    """Response after creating an application."""
    id: str
    status: str
    message: str


class NamespacePatchRequest(BaseModel):
    """Generic namespace patch — agents send arbitrary JSON."""
    class Config:
        extra = "allow"


class NoteRequest(BaseModel):
    """Human note from the credit officer."""
    note: str
    author: str = "anonymous"


class StressTriggerRequest(BaseModel):
    """Re-trigger stress test with custom parameters."""
    interest_rate_hike: float = 2.0
    revenue_drop_pct: float = 20.0


class FileUploadResponse(BaseModel):
    """Response after file upload."""
    storage_path: str
    file_url: str
    status: str = "UPLOADED"
