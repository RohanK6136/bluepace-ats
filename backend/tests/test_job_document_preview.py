from app.main import _extract_job_document_fields, _infer_employment_type, _infer_job_department
from app.services import extractor as extractor_module
from app.services import matching as matching_module


def test_infer_job_department_prefers_title():
    assert _infer_job_department("Senior Backend Python Engineer", "Build APIs and maintain databases.") == "Engineering"
    assert _infer_job_department("Senior Data Scientist", "Work with Python, SQL and analytics.") == "Data & Analytics"


def test_infer_employment_type():
    assert _infer_employment_type("This is a 6 month internship.") == "Internship"
    assert _infer_employment_type("Part-time role, 20 hours per week.") == "Part-time"
    assert _infer_employment_type("Permanent full-time position.") == "Full-time"


def test_extract_job_document_fields_maps_review_form(monkeypatch):
    monkeypatch.setattr(
        extractor_module.extractor_service,
        "extract_to_json",
        lambda content, filename: {
            "raw_text": (
                "Senior Backend Python Engineer\n"
                "Hyderabad, India\n"
                "4+ years experience\n"
                "Python FastAPI PostgreSQL Docker\n"
                "Responsibilities\n"
                "- Build APIs\n"
                "- Improve platform reliability\n"
            ),
            "document_extraction_engine": "docling",
        },
    )
    monkeypatch.setattr(
        matching_module.matching_service,
        "parse_job_description",
        lambda title, description, location=None: {
            "required_skills": ["Python", "FastAPI", "PostgreSQL"],
            "preferred_skills": ["Docker"],
            "location": location or "Hyderabad, India",
            "work_mode": "hybrid",
            "minimum_experience_years": 4,
            "responsibilities": ["Build APIs", "Improve platform reliability"],
            "education": "Bachelor's degree",
        },
    )

    fields = _extract_job_document_fields(b"jd", "jd.pdf")

    assert fields["title"] == "Senior Backend Python Engineer"
    assert fields["department"] == "Engineering"
    assert fields["location"] == "Hyderabad, India"
    assert fields["work_mode"] == "hybrid"
    assert fields["minimum_experience_years"] == 4
    assert fields["required_skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert fields["responsibilities"] == ["Build APIs", "Improve platform reliability"]
    assert fields["extraction_engine"] == "docling"

def test_extractor_defaults_to_docling(monkeypatch):
    monkeypatch.delenv("DOCUMENT_EXTRACTION_ENGINE", raising=False)
    monkeypatch.delenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", raising=False)
    service = extractor_module.DocumentExtractor()
    assert service.extraction_engine == "docling"
    assert service.fallback_extraction_engine == "legacy"


def test_extractor_engine_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "legacy")
    monkeypatch.setenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "docling")
    service = extractor_module.DocumentExtractor()
    assert service.extraction_engine == "legacy"
    assert service.fallback_extraction_engine == "docling"
