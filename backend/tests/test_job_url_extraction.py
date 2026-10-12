import app.main as api


def _parse_html(html: str) -> api._JobPageParser:
    parser = api._JobPageParser()
    parser.feed(html)
    parser.close()
    return parser


def test_existing_extraction_still_wins_when_usable(monkeypatch):
    description = "Existing readable job description with responsibilities and qualifications."
    html = f"<html><body><main><p>{description}</p></main></body></html>"
    parser = _parse_html(html)

    def unexpected_extraction(*args, **kwargs):
        raise AssertionError("Trafilatura should not run when existing extraction is usable")

    monkeypatch.setattr(api.trafilatura, "extract", unexpected_extraction)

    assert api._extract_job_description(html, parser) == description


def test_trafilatura_fallback_extracts_text_when_existing_result_is_too_short(monkeypatch):
    html = "<html><body><nav>Home Careers Sign in</nav><div id='app'></div></body></html>"
    parser = _parse_html(html)
    extracted = (
        "Senior Python Engineer. Responsibilities include developing APIs, "
        "reviewing code, and supporting production systems. "
        "Requirements include Python, SQL, and cloud experience."
    )
    calls = {}

    def fake_extract(document, **kwargs):
        calls["html"] = document
        calls["kwargs"] = kwargs
        return extracted

    monkeypatch.setattr(api.trafilatura, "extract", fake_extract)

    result = api._extract_job_description(html, parser)

    assert result == extracted
    assert calls["html"] == html
    assert calls["kwargs"] == {"include_comments": False, "include_tables": True}


def test_trafilatura_empty_result_preserves_existing_partial_extraction(monkeypatch):
    html = "<html><body><p>Only a short title.</p></body></html>"
    parser = _parse_html(html)
    monkeypatch.setattr(api.trafilatura, "extract", lambda *args, **kwargs: None)

    result = api._extract_job_description(html, parser)

    assert result == "Only a short title."


def test_trafilatura_failure_does_not_break_existing_partial_extraction(monkeypatch):
    html = "<html><body><p>Only a short title.</p></body></html>"
    parser = _parse_html(html)

    def fail_extraction(*args, **kwargs):
        raise RuntimeError("Extractor failure")

    monkeypatch.setattr(api.trafilatura, "extract", fail_extraction)

    assert api._extract_job_description(html, parser) == "Only a short title."
