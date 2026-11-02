"""Resume authorship review endpoint.

This reports observable text-quality signals only. It does not infer or classify
whether a resume was written by a human or an AI system.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require_api_key
from app.features.resume_authorship.analysis import assess_resume_text
from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES

router = APIRouter(
    prefix="/v1/resume-authorship",
    tags=["Resume Authorship Review"],
    dependencies=[Depends(require_api_key)],
)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_TEXT_CHARACTERS = 60_000
MIN_TEXT_CHARACTERS = 100


class ResumeAuthorshipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(
        min_length=MIN_TEXT_CHARACTERS,
        max_length=MAX_TEXT_CHARACTERS,
        description="Extracted resume text. Avoid sending unnecessary personal information.",
    )


class ReviewSignalResponse(BaseModel):
    code: str
    label: str
    detail: str
    severity: str = "low"


class ResumeAuthorshipResponse(BaseModel):
    assessment: Literal["undetermined"]
    status: Literal["insufficient_evidence", "review_recommended", "no_text_quality_alerts"]
    confidence: Literal["not_assessed"]
    text_characters: int
    signals: list[ReviewSignalResponse]
    limitations: list[str]
    human_review_required: bool
    detector_version: str


def _assess(text: str) -> ResumeAuthorshipResponse:
    cleaned = text.strip()
    if len(cleaned) < MIN_TEXT_CHARACTERS:
        raise HTTPException(
            status_code=422,
            detail=f"At least {MIN_TEXT_CHARACTERS} characters of extracted resume text are required.",
        )
    try:
        result = assess_resume_text(cleaned)
    except ValueError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    return ResumeAuthorshipResponse.model_validate(result)


def _extract_resume_text(data: bytes, filename: str) -> str:
    """Extract text locally; no model/provider call and no file persistence."""
    extension = Path(filename).suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    if len(data) > MAX_DOCUMENT_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Resume file exceeds the 5 MB upload limit.")
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded resume is empty.")

    if extension in {".txt", ".md"}:
        try:
            return data.decode("utf-8-sig").strip()
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=422, detail="Text resume must be UTF-8 encoded.") from error

    if extension == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                try:
                    if not reader.decrypt(""):
                        raise ValueError("password-protected PDF")
                except Exception as error:
                    raise ValueError("password-protected PDF") from error
            parts = [page.extract_text() or "" for page in reader.pages]
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Unable to read PDF: {error}") from error
        extracted = "\n".join(parts).strip()
        if not extracted:
            raise HTTPException(
                status_code=422,
                detail="No selectable text was found in this PDF. Scanned/image-only PDFs need OCR before review.",
            )
        return extracted

    try:
        from docx import Document

        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if values:
                    parts.append(" | ".join(values))
        for section in document.sections:
            parts.extend(
                paragraph.text
                for paragraph in section.header.paragraphs
                if paragraph.text.strip()
            )
            parts.extend(
                paragraph.text
                for paragraph in section.footer.paragraphs
                if paragraph.text.strip()
            )
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"Unable to read DOCX: {error}") from error

    extracted = "\n".join(parts).strip()
    if not extracted:
        raise HTTPException(status_code=422, detail="No readable text was found in this DOCX.")
    return extracted


@router.post(
    "/assess",
    response_model=ResumeAuthorshipResponse,
    summary="Review observable resume text-quality signals",
)
def assess_resume_authorship(payload: ResumeAuthorshipRequest) -> ResumeAuthorshipResponse:
    """Assess pasted/extracted text without calling an LLM or storing the resume."""
    return _assess(payload.text)


@router.post(
    "/assess/upload",
    response_model=ResumeAuthorshipResponse,
    summary="Extract and review a resume file",
    description=(
        "Accepts one PDF, DOCX, TXT or MD file. Text extraction runs locally; no LLM is called and the "
        "uploaded file/text is not persisted. Scanned PDFs are rejected with an OCR requirement. "
        "The result is a text-quality review, not an AI-authorship verdict."
    ),
)
async def assess_resume_authorship_upload(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
) -> ResumeAuthorshipResponse:
    has_file = file is not None and bool(file.filename)
    has_text = bool(text and text.strip())
    if has_file == has_text:
        raise HTTPException(
            status_code=422,
            detail="Send exactly one source: a resume file or extracted resume text.",
        )

    if has_file:
        assert file is not None
        data = await file.read(MAX_DOCUMENT_SIZE_BYTES + 1)
        if len(data) > MAX_DOCUMENT_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="Resume file exceeds the 5 MB upload limit.")
        extracted = _extract_resume_text(data, file.filename or "resume")
    else:
        extracted = (text or "").strip()
        if len(extracted) > MAX_TEXT_CHARACTERS:
            raise HTTPException(status_code=413, detail="Resume text exceeds the 60000 character limit.")

    return _assess(extracted)


def _install_extractor_text_quality_hook() -> None:
    """Ensure every extract_to_json result carries text_quality_review for intake paths."""
    try:
        from app.services.extractor import extractor_service
        from app.features.resume_authorship.analysis import build_text_quality_review
    except Exception:
        return
    if getattr(extractor_service.extract_to_json, "_text_quality_hook", False):
        return
    original = extractor_service.extract_to_json

    def wrapped(file_content: bytes, filename: str):
        parsed = original(file_content, filename)
        if isinstance(parsed, dict) and "text_quality_review" not in parsed:
            try:
                review = build_text_quality_review(parsed.get("raw_text"))
                if review is not None:
                    parsed = dict(parsed)
                    parsed["text_quality_review"] = review
            except Exception:
                pass
        return parsed

    wrapped._text_quality_hook = True  # type: ignore[attr-defined]
    extractor_service.extract_to_json = wrapped  # type: ignore[method-assign]


_install_extractor_text_quality_hook()
