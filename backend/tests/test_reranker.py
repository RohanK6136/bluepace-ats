from app.services.reranker import RerankerService


def test_reranker_is_safe_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "false")
    service = RerankerService()
    assert service.configured is False
    assert service.rerank("python backend engineer", [{"text": "Python FastAPI"}]) == []
