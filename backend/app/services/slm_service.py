import json
import os
import re

from openai import OpenAI


class SLMService:
    """Optional Small Language Model enrichment kept outside the HTTP request path."""

    def __init__(self):
        self.enabled = os.getenv("ENABLE_SLM_RESUME_ENRICHMENT", "false").strip().lower() == "true"
        self.base_url = os.getenv("SLM_BASE_URL", "").strip() or None
        self.api_key = os.getenv("SLM_API_KEY", "").strip() or None
        self.model = os.getenv("SLM_MODEL", "qwen2.5:3b").strip()
        try:
            timeout = float(os.getenv("SLM_TIMEOUT_SECONDS", "2.0"))
        except ValueError:
            timeout = 2.0

        if self.enabled:
            kwargs = {"api_key": self.api_key or "local-slm", "timeout": max(0.5, timeout), "max_retries": 0}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            elif os.getenv("OPENROUTER_API_KEY"):
                kwargs["base_url"] = "https://openrouter.ai/api/v1"
                kwargs["api_key"] = os.getenv("OPENROUTER_API_KEY")
            self.client = OpenAI(**kwargs)
        else:
            self.client = None

    @staticmethod
    def _json_from_response(content: str) -> dict | None:
        cleaned = (content or "").strip()
        if not cleaned:
            return None
        fenced = re.search(r"\x60\x60\x60(?:json)?\s*(.*?)\s*\x60\x60\x60", cleaned, re.IGNORECASE | re.DOTALL)
        candidate = fenced.group(1) if fenced else cleaned
        try:
            data = json.loads(candidate)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def enrich_resume(self, resume_json: dict) -> dict | None:
        if not self.enabled or self.client is None:
            return None

        profile = {
            key: value
            for key, value in (resume_json or {}).items()
            if key not in {"raw_text", "slm_enrichment"}
        }
        prompt = (
            "You are a lightweight resume enrichment model. Extract only facts already present "
            "in the supplied structured resume. Do not invent facts. Return JSON with exactly these "
            "keys: normalized_skills (array of strings), role_keywords (array of strings), "
            "education_level (string or null), experience_years (number or null), "
            "summary (string). Keep arrays concise.\n\n"
            f"Resume profile:\n{json.dumps(profile, ensure_ascii=True)[:18000]}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=500,
            )
            data = self._json_from_response(response.choices[0].message.content or "")
            if not data:
                return None

            normalized_skills = data.get("normalized_skills")
            role_keywords = data.get("role_keywords")
            summary = data.get("summary")
            return {
                "normalized_skills": (
                    [str(value).strip() for value in normalized_skills if str(value).strip()][:50]
                    if isinstance(normalized_skills, list)
                    else []
                ),
                "role_keywords": (
                    [str(value).strip() for value in role_keywords if str(value).strip()][:30]
                    if isinstance(role_keywords, list)
                    else []
                ),
                "education_level": (
                    str(data["education_level"]).strip()[:200]
                    if data.get("education_level") is not None
                    else None
                ),
                "experience_years": (
                    float(data["experience_years"])
                    if isinstance(data.get("experience_years"), (int, float))
                    and 0 <= float(data["experience_years"]) <= 60
                    else None
                ),
                "summary": str(summary).strip()[:1000] if summary else "",
            }
        except Exception:
            # SLM is strictly additive. A failed enrichment must never fail extraction.
            return None


slm_service = SLMService()
