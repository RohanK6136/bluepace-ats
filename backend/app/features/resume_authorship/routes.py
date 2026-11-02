"""Resume authorship review endpoint; reports text-quality signals, not AI verdicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require_api_key
from app.features.resume_authorship.analysis import assess_resume_text

router = APIRouter(
    prefix="/v1/resume-authorship",
    tags=["Resume Authorship Review"],
    dependencies=[Depends(require_api_key)],
)


class ResumeAuthorshipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=60_000, description="Extracted resume text; do not include unnecessary personal data")


@router.post("/assess", summary="Review observable resume text-quality signals")
def assess_resume_authorship(payload: ResumeAuthorshipRequest) -> dict:
    """Return conservative text-quality flags. This endpoint does not detect AI authorship."""
    text = payload.text.strip()
    if len(text) < 100:
        raise HTTPException(status_code=422, detail="At least 100 characters of extracted resume text are required")
    try:
        return assess_resume_text(text)
    except ValueError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
