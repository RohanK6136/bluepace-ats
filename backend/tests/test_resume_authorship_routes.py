"""API tests for resume text-quality review.

The feature deliberately returns no AI-authorship prediction. Tests cover JSON
and uploaded-file paths and verify that files are extracted in memory only.
"""

from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from docx import Document
from reportlab.pdfgen import canvas

from app.api.deps import require_api_key
from app.features.resume_authorship.routes import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def sample_resume_text() -> str:
    return "\n".join(
        f"Experience item {index}: built and maintained reliable Python services for internal teams."
        for index in range(12)
    )


def make_docx(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def make_pdf(text: str) -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output)
    page.drawString(40, 780, text)
    page.save()
    return output.getvalue()


def assert_non_verdict_response(payload: dict) -> None:
    assert payload["assessment"] == "undetermined"
    assert payload["confidence"] == "not_assessed"
    assert payload["human_review_required"] is True
    assert payload["detector_version"] == "text-quality-signals-0.1.0"
    assert any("cannot reliably determine" in item for item in payload["limitations"])


def test_json_text_endpoint_returns_non_verdict_quality_review() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess",
        json={"text": sample_resume_text()},
    )
    assert response.status_code == 200
    assert_non_verdict_response(response.json())


def test_text_file_upload_is_supported() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("candidate.txt", sample_resume_text().encode(), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["text_characters"] > 100
    assert_non_verdict_response(response.json())


def test_docx_upload_extracts_paragraph_text() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("candidate.docx", make_docx(sample_resume_text()), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 200
    assert_non_verdict_response(response.json())


def test_pdf_upload_extracts_selectable_text() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("candidate.pdf", make_pdf(sample_resume_text()), "application/pdf")},
    )
    assert response.status_code == 200
    assert_non_verdict_response(response.json())


def test_scanned_or_image_only_pdf_is_rejected_with_ocr_guidance() -> None:
    output = BytesIO()
    page = canvas.Canvas(output)
    page.showPage()
    page.save()
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("scanned.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_upload_rejects_unsupported_extension() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("candidate.exe", b"not a resume", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_upload_requires_exactly_one_source() -> None:
    client = make_client()
    no_source = client.post("/v1/resume-authorship/assess/upload", data={})
    both_sources = client.post(
        "/v1/resume-authorship/assess/upload",
        data={"text": sample_resume_text()},
        files={"file": ("candidate.txt", sample_resume_text().encode(), "text/plain")},
    )
    assert no_source.status_code == 422
    assert both_sources.status_code == 422


def test_upload_rejects_text_below_minimum_length() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("short.txt", b"Python developer resume.", "text/plain")},
    )
    assert response.status_code == 422


def test_upload_rejects_files_over_five_megabytes() -> None:
    response = make_client().post(
        "/v1/resume-authorship/assess/upload",
        files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")},
    )
    assert response.status_code == 413
