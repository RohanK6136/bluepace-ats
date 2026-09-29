import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

class LLMValidator:
    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("⚠️ WARNING: OPENROUTER_API_KEY is not set in .env")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or "missing-key",
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
            print("🔄 Sending request to OpenRouter...")
            response = self.client.chat.completions.create(
                model="qwen/qwen-2.5-72b-instruct",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=3000,
            )
            content = response.choices[0].message.content
            print("✅ Received response from OpenRouter.")
            parsed = self._parse_llm_response(content)
            return parsed
        except Exception as e:
            print(f"❌ LLM Error: {str(e)}")
            return {
                "error": str(e),
                "match_score": 0, "coding_skills_score": 0, "behavioral_skills_score": 0,
                "mandatory_skills_match_score": 0, "mandatory_skills_met": [], "mandatory_skills_missed": [],
                "summary": f"Validation failed: {str(e)}", "missing_skills": [], "recommendation": "Error",
                "is_fresher": False, "highest_education": "N/A",
                "extracted_experience": [], "extracted_education": [],
                "extracted_hobbies": [], "extracted_university_projects": []
            }

llm_validator = LLMValidator()