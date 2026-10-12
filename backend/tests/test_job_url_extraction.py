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

def test_jsonld_jobposting_description_remains_preferred(monkeypatch):
    description = "Structured description with enough text to remain the preferred source."
    html = (
        '<html><head><script type="application/ld+json">'
        + __import__("json").dumps({
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Backend Engineer",
            "description": description,
        })
        + "</script></head><body><p>Other visible page content is different.</p></body></html>"
    )
    parser = _parse_html(html)

    def unexpected_extraction(*args, **kwargs):
        raise AssertionError("Trafilatura should not run for a usable JobPosting description")

    monkeypatch.setattr(api.trafilatura, "extract", unexpected_extraction)

    assert api._extract_job_description(html, parser) == description


def test_fetch_job_page_preserves_metadata_with_trafilatura_fallback(monkeypatch):
    import json

    url = "https://jobs.example.com/role/123"
    html = (
        "<html><head><title>Careers</title><script type='application/ld+json'>"
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Machine Learning Engineer",
            "description": "short",
            "employmentType": "FULL_TIME",
            "jobLocation": {"address": {"addressLocality": "Hyderabad"}},
        })
        + "</script></head><body><div id='app'></div></body></html>"
    )
    description = (
        "Build machine learning systems, collaborate with engineering teams, "
        "write production Python, and evaluate models. Requirements include "
        "Python, SQL, machine learning fundamentals, and cloud deployment."
    )

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return html.encode("utf-8")

        def geturl(self):
            return url

    monkeypatch.setattr(api, "_validate_public_job_url", lambda value: value)
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    monkeypatch.setattr(api.trafilatura, "extract", lambda *args, **kwargs: description)

    final_url, title, payload = api._fetch_job_page(url)

    assert final_url == url
    assert title == "Machine Learning Engineer"
    assert payload["description"] == description
    assert payload["employment_type"] == "FULL_TIME"
    assert payload["location"] == "Hyderabad"
