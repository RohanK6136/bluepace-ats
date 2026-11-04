"""Regression tests for JD upload metadata extraction and streamed model parsing."""

from app.config import Settings
from app.core.ingest import ingest_text
from app.features.jd_standardizer.pipeline.candidates import find_candidates
from app.features.jd_standardizer.pipeline.clean import clean
from app.features.jd_standardizer.pipeline.generate import parse_streamed_generation, title_guess
from app.features.jd_standardizer.pipeline.models import Overrides
from app.features.jd_standardizer.pipeline.policy import load_policy
from app.features.jd_standardizer.pipeline.segment import segment
from app.features.jd_standardizer.pipeline.validate import validate


def _analyse(text: str):
    settings = Settings()
    policy = load_policy()
    raw = ingest_text(text)
    cleaned = clean(raw, policy, settings)
    segmented = segment(cleaned, policy, settings)
    candidates = find_candidates(cleaned, segmented, policy)
    validated = validate(cleaned, segmented, candidates, None, Overrides(), policy, settings)
    return raw, cleaned, validated


def test_two_line_jd_metadata_populates_publication_fields():
    text = "\\n".join(
        [
            "BluePace Tech | Job Description | Python Full Stack Developer",
            "Python Full Stack Developer",
            "Job Description | Engineering | BluePace Tech",
            "Job Title",
            "Python Full Stack Developer",
            "Employment Type",
            "Full-Time",
            "Country",
            "India",
            "Location",
            "Hyderabad, Telangana, India",
            "Work Model",
            "Hybrid",
            "Experience",
            "2-4 years",
            "Department",
            "Engineering",
            "About the Role",
            "Build and maintain reliable web applications with Python and React.",
            "Key Responsibilities",
            "• Design, develop, test, and maintain REST APIs.",
            "Required Qualifications",
            "• Strong programming experience in Python and FastAPI.",
            "• Experience building frontend applications with React.",
            "• Working knowledge of SQL and relational databases.",
        ]
    )

    raw, cleaned, fields = _analyse(text)
    normalized_lines = [line.text for line in raw]

    assert "Job Title: Python Full Stack Developer" in normalized_lines
    assert "Employment Type: Full-Time" in normalized_lines
    assert "Country: India" in normalized_lines
    assert fields.fields["role_type"].value == "Full-Time"
    assert fields.fields["country"].value == {"iso2": "IN", "name": "India"}
    assert title_guess(cleaned, fields) == "Python Full Stack Developer"


def test_metadata_in_docx_style_table_rows_is_normalized():
    raw = ingest_text(
        "Job Title | Python Full Stack Developer\\n"
        "Employment Type | Full-Time\\n"
        "Country | India"
    )
    lines = [line.text for line in raw]

    assert lines == [
        "Job Title: Python Full Stack Developer",
        "Employment Type: Full-Time",
        "Country: India",
    ]


def test_stream_parser_strips_qwen_think_block_before_json_parse():
    parsed = parse_streamed_generation(
        [
            "<think>Let me inspect the source and prepare the result.</think>\\n",
            '{"title":"Python Full Stack Developer","facts":{"employment_type":"Full-Time"}}',
        ]
    )

    assert parsed["title"] == "Python Full Stack Developer"
    assert parsed["facts"]["employment_type"] == "Full-Time"
