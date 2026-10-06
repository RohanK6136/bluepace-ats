import os
import json
import re
import time
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

OPENROUTER_TIMEOUT_SECONDS = 20.0

# Task-based routing: deterministic code first, fast model for routine AI,
# stronger model only for genuinely ambiguous reasoning.
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
ASSISTANT_MODEL = os.getenv("OPENROUTER_ASSISTANT_MODEL", DEFAULT_MODEL)
DEEP_REASONING_MODEL = os.getenv("OPENROUTER_DEEP_REASONING_MODEL", "openai/gpt-5.5")
VALIDATION_MODEL = os.getenv("OPENROUTER_VALIDATION_MODEL", DEFAULT_MODEL)

class LLMValidator:
    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("⚠️ WARNING: OPENROUTER_API_KEY is not set in .env")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or "missing-key",
            timeout=OPENROUTER_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.model = DEFAULT_MODEL
        configured_fallbacks = os.getenv(
            "OPENROUTER_FALLBACK_MODELS",
            "meta-llama/llama-3.3-70b-instruct,google/gemini-2.5-flash",
        )
        self.fallback_models = list(
            dict.fromkeys(model.strip() for model in configured_fallbacks.split(",") if model.strip())
        )[:3]
        try:
            configured_retries = int(os.getenv("OPENROUTER_429_RETRIES", "1"))
        except ValueError:
            configured_retries = 1
        self.rate_limit_retries = max(0, min(configured_retries, 2))
        self.sleep = time.sleep

    @staticmethod
    def _is_rate_limited(error):
        if getattr(error, "status_code", None) == 429:
            return True
        return bool(re.search(r"\b429\b", str(error)))

    @staticmethod
    def _retry_delay(error, attempt):
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        try:
            return max(0.0, min(float(retry_after), 5.0)) if retry_after is not None else min(0.5 * (2 ** attempt), 2.0)
        except (TypeError, ValueError):
            return min(0.5 * (2 ** attempt), 2.0)

    def _request_completion(self, prompt, model=None, temperature=0.1, max_tokens=3000):
        selected_model = model or self.model
        extra_body = {
            "provider": {
                "sort": "throughput",
                "allow_fallbacks": True,
            }
        }
        if self.fallback_models:
            extra_body["models"] = self.fallback_models

        for attempt in range(self.rate_limit_retries + 1):
            try:
                return self.client.chat.completions.create(
                    model=selected_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                )
            except Exception as error:
                if not self._is_rate_limited(error) or attempt >= self.rate_limit_retries:
                    raise
                delay = self._retry_delay(error, attempt)
                print(f"OpenRouter rate-limited validation; retrying after {delay:.1f}s")
                self.sleep(delay)

    def request_assistant(self, prompt, deep=False):
        """Run recruiter-assistant generation with an explicit task policy."""
        return self._request_completion(
            prompt,
            model=DEEP_REASONING_MODEL if deep else ASSISTANT_MODEL,
            temperature=0.1,
            max_tokens=2200,
        )

    def request_validation(self, prompt):
        """Run secondary resume/JD validation after deterministic extraction."""
        return self._request_completion(
            prompt,
            model=VALIDATION_MODEL,
            temperature=0.0,
            max_tokens=2200,
        )

    @staticmethod
    def _normalize_score(value, default=0):
        if value is None:
            return default
        if isinstance(value, (int, float)):
            score = float(value)
        elif isinstance(value, str):
            cleaned = value.strip().replace('%', '').replace(',', '')
            match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
            if not match:
                return default
            score = float(match.group(0))
        else:
            return default

        score = max(0, min(100, round(score)))
        return int(score)

    @classmethod
    def _parse_llm_response(cls, raw_content):
        if raw_content is None:
            raise ValueError("Empty LLM response")

        text = str(raw_content).strip()
        if not text:
            raise ValueError("Empty LLM response")

        fenced_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, flags=re.DOTALL | re.IGNORECASE)
        if fenced_match:
            text = fenced_match.group(1)
        else:
            start_index = text.find('{')
            end_index = text.rfind('}')
            if 0 <= start_index < end_index:
                text = text[start_index:end_index + 1]

        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM response was not a JSON object")

        for key in [
            "match_score",
            "coding_skills_score",
            "behavioral_skills_score",
            "mandatory_skills_match_score",
        ]:
            payload[key] = cls._normalize_score(payload.get(key), 0)

        return payload

    def validate_resume(self, resume_json: dict, job_description: str) -> dict:
        resume_data = dict(resume_json)
        raw_text = resume_data.pop("raw_text", "")

        prompt = f"""
        You are an expert ATS validator. Evaluate the candidate's resume against the Job Description (JD).
        Extract: Work Experience, Education (Degree, University, CGPA, Year), Hobbies, University Projects, Fresher Status, Highest Education, and Mandatory Skills Match.

        Job Description:
        {job_description}

        Candidate Resume Data:
        {json.dumps(resume_data, indent=2)}

        Raw Resume Text:
        {raw_text[:4000]}

        Return ONLY a valid JSON object with this exact schema:
        {{
            "match_score": <int 0-100>, 
            "coding_skills_score": <int 0-100>, 
            "behavioral_skills_score": <int 0-100>,
            "mandatory_skills_match_score": <int 0-100>, 
            "mandatory_skills_met": [<str>], 
            "mandatory_skills_missed": [<str>],
            "summary": "<str>", 
            "missing_skills": [<str>], 
            "recommendation": "<Strong Yes, Yes, Maybe, No>",
            "is_fresher": <bool>, 
            "highest_education": "<str>",
            "extracted_experience": [{{"company": "<str>", "title": "<str>", "duration": "<str>", "description": "<str>"}}],
            "extracted_education": [{{"degree": "<str>", "university": "<str>", "cgpa": "<str>", "graduation_year": "<str>"}}],
            "extracted_hobbies": ["<str>"], 
            "extracted_university_projects": ["<str>"]
        }}
        """
        try:
            print("Sending resume validation request through OpenRouter")
            response = self.request_validation(prompt)
            content = response.choices[0].message.content
            print("Received resume validation response")
            parsed = self._parse_llm_response(content)
            return parsed
        except Exception as error:
            if self._is_rate_limited(error):
                safe_error = (
                    "All configured AI providers are temporarily rate-limited. "
                    "Please retry shortly or configure an OpenRouter provider key."
                )
            else:
                safe_error = str(error)[:1000]
            print(f"Resume validation unavailable: {safe_error}")
            return {
                "error": safe_error,
                "match_score": 0, "coding_skills_score": 0, "behavioral_skills_score": 0,
                "mandatory_skills_match_score": 0, "mandatory_skills_met": [], "mandatory_skills_missed": [],
                "summary": f"Validation unavailable: {safe_error}", "missing_skills": [], "recommendation": "Manual Review",
                "is_fresher": False, "highest_education": "N/A",
                "extracted_experience": [], "extracted_education": [],
                "extracted_hobbies": [], "extracted_university_projects": []
            }

llm_validator = LLMValidator()