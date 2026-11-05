from scripts.resume_extraction_benchmark import (
    build_benchmark_cases,
    run_benchmark,
    score_field,
)


def test_benchmark_corpus_contains_pdf_docx_and_two_column_cases():
    cases = build_benchmark_cases()

    assert {case.name for case in cases} == {
        "text_pdf_single_column",
        "docx_experience_and_education_tables",
        "text_pdf_two_column_layout",
    }
    assert all(case.content for case in cases)
    assert all(case.expected["email"].endswith("@example.test") for case in cases)


def test_field_scoring_reports_precision_recall_and_f1():
    result = score_field(
        "skills",
        ["Python", "FastAPI", "PostgreSQL"],
        ["Python", "FastAPI", "React"],
    )

    assert result["true_positive"] == 2
    assert result["false_positive"] == 1
    assert result["false_negative"] == 1
    assert result["precision"] == 0.6667
    assert result["recall"] == 0.6667
    assert result["f1"] == 0.6667


def test_benchmark_runs_real_local_extractors_without_provider_calls(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "docling")
    monkeypatch.setenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "docling")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-used-by-benchmark")

    report = run_benchmark()

    assert report["benchmark"] == "bluepace_synthetic_resume_extraction_v1"
    assert report["corpus"] == "synthetic_only"
    assert report["provider_calls"] == 0
    assert report["document_count"] == 3
    assert all(item["status"] == "extracted" for item in report["results"])
    assert all(item["latency_ms"] >= 0 for item in report["results"])
    assert "must-not-be-used-by-benchmark" == __import__("os").environ["OPENROUTER_API_KEY"]
    assert __import__("os").environ["DOCUMENT_EXTRACTION_ENGINE"] == "docling"
    assert __import__("os").environ["ENABLE_LLM_RESUME_ENRICHMENT"] == "true"


def test_single_column_pdf_and_docx_recover_expected_profile_fields(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "legacy")
    monkeypatch.setenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "disabled")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    report = run_benchmark()
    by_name = {item["case"]: item for item in report["results"]}

    for name in ("text_pdf_single_column", "docx_experience_and_education_tables"):
        result = by_name[name]
        assert result["status"] == "extracted"
        for field in ("name", "email", "phone", "skills", "experience", "education"):
            assert result["fields"][field]["f1"] == 1.0, (
                name,
                field,
                result["fields"][field],
            )
