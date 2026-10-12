from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as api


def test_fetch_job_page_uses_rendered_browser_fallback_when_raw_html_is_a_shell(monkeypatch):
    url = "https://jobs.example.com/role/123"
    raw_html = "<html><head></head><body>JPMC Candidate Experience page</body></html>"
    rendered_html = (
        "<html><head><title>Candidate Experience</title>"
        "<meta name='location' content='Hyderabad'></head>"
        "<body><main><h1>Lead Software Engineer - Python Full Stack Developer</h1>"
        "<section><p>Design, build, test, and support production Python services. "
        "Collaborate with engineering and product teams. Required skills include "
        "Python, SQL, REST APIs, cloud platforms, code review, and automated testing.</p>"
        "</section></main></body></html>"
    )
    rendered_text = (
        "Lead Software Engineer - Python Full Stack Developer. Design, build, test, "
        "and support production Python services. Required skills include Python, SQL, "
        "REST APIs, cloud platforms, code review, and automated testing."
    )

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return raw_html.encode("utf-8")

        def geturl(self):
            return url

    monkeypatch.setattr(api, "_validate_public_job_url", lambda value: value)
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    monkeypatch.setattr(api.trafilatura, "extract", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "_render_job_page",
        lambda value: (url, "Lead Software Engineer - Python Full Stack Developer", rendered_html, rendered_text),
    )

    final_url, title, payload = api._fetch_job_page(url)

    assert final_url == url
    assert title == "Lead Software Engineer - Python Full Stack Developer"
    assert "production Python services" in payload["description"]
    assert payload["location"] == "Hyderabad"
    assert payload["source"] == "Job URL import"


def test_browser_request_guard_aborts_unsafe_subrequests(monkeypatch):
    route = SimpleNamespace(
        request=SimpleNamespace(url="http://127.0.0.1/admin"),
        aborted=False,
        continued=False,
    )
    route.abort = lambda: setattr(route, "aborted", True)
    route.continue_ = lambda: setattr(route, "continued", True)

    def reject_private_url(_url):
        raise HTTPException(status_code=400, detail="The job URL must point to a public internet host.")

    monkeypatch.setattr(api, "_validate_public_job_url", reject_private_url)

    api._guard_browser_route(route)

    assert route.aborted is True
    assert route.continued is False


def test_browser_request_guard_allows_validated_public_subrequests(monkeypatch):
    url = "https://static.example.com/app.js"
    route = SimpleNamespace(
        request=SimpleNamespace(url=url),
        aborted=False,
        continued=False,
    )
    route.abort = lambda: setattr(route, "aborted", True)
    route.continue_ = lambda: setattr(route, "continued", True)
    monkeypatch.setattr(api, "_validate_public_job_url", lambda value: value)

    api._guard_browser_route(route)

    assert route.continued is True
    assert route.aborted is False
