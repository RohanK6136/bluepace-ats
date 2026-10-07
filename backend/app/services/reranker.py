"""Optional second-stage semantic reranker.

The ATS first retrieves/ranks locally. This service only runs when explicitly
enabled and a Cohere API key is configured. Failures return no rerank data so
the deterministic ranking remains the safe fallback.
"""

import json
import os
import time
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


class RerankerService:
    def __init__(self):
        self.enabled = os.getenv("RERANK_ENABLED", "false").strip().lower() == "true"
        self.api_key = os.getenv("COHERE_API_KEY", "").strip()
        self.url = os.getenv("COHERE_RERANK_URL", "https://api.cohere.com/v2/rerank").strip()
        self.model = os.getenv("RERANK_MODEL", "rerank-v4.0-fast").strip()
        try:
            self.timeout = max(1.0, float(os.getenv("RERANK_TIMEOUT_SECONDS", "8")))
        except ValueError:
            self.timeout = 8.0
        try:
            self.max_documents = max(2, min(50, int(os.getenv("RERANK_MAX_DOCUMENTS", "30"))))
        except ValueError:
            self.max_documents = 30

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def rerank(self, query: str, documents: list[dict], top_n: int | None = None) -> list[dict]:
        if not self.configured or not documents:
            return []

        selected = documents[: self.max_documents]
        payload = {
            "model": self.model,
            "query": str(query or "")[:4000],
            "documents": [str(item.get("text") or "")[:12000] for item in selected],
            "top_n": max(1, min(top_n or len(selected), len(selected))),
        }
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            self.url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            results = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list):
                return []
            output = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                try:
                    index = int(item.get("index"))
                    relevance = float(item.get("relevance_score", 0.0))
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(selected):
                    output.append({
                        "index": index,
                        "relevance_score": max(0.0, min(1.0, relevance)),
                    })
            return output
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError):
            return []
        finally:
            self.last_latency_ms = round((time.perf_counter() - started) * 1000, 1)


reranker_service = RerankerService()
