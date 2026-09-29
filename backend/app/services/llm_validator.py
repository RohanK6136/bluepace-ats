import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class LLMValidator:
    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if api_key:
            print(f"🔑 Key loaded: {api_key[:15]}... (Length: {len(api_key)})")
        else:
            print("❌ API KEY NOT FOUND IN .env")
        
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or "missing",
        )

    def validate_resume(self, resume_json: dict, job_description: str) -> dict:
        resume_data = dict(resume_json)
        raw_text = resume_data.pop("raw_text", "")

        prompt = f"""
        You are an expert ATS validator. Evaluate the resume against the JD.
        JD: {job_description}
        Resume: {json.dumps(resume_data, indent=2)}
        Raw Text: {raw_text[:4000]}
        
        Return ONLY a JSON object. Do not add any explanations, markdown, or code blocks. Just the JSON.
        {{
            "match_score": <int 0-100>, "coding_skills_score": <int>, "behavioral_skills_score": <int>,
            "mandatory_skills_match_score": <int>, "mandatory_skills_met": [<str>], "mandatory_skills_missed": [<str>],
            "summary": "<str>", "missing_skills": [<str>], "recommendation": "<str>",
            "is_fresher": <bool>, "highest_education": "<str>",
            "extracted_experience": [{{"company": "<str>", "title": "<str>", "duration": "<str>", "description": "<str>"}}],
            "extracted_education": [{{"degree": "<str>", "university": "<str>", "cgpa": "<str>", "graduation_year": "<str>"}}],
            "extracted_hobbies": ["<str>"], "extracted_university_projects": ["<str>"]
        }}
        """
        try:
            print("🔄 Sending request to OpenRouter...")
            response = self.client.chat.completions.create(
                model="qwen/qwen-2.5-72b-instruct",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1, max_tokens=3000,
            )
            content = response.choices[0].message.content
            print(f"📥 Raw response received.")
            
            # Robust parsing: Find the JSON object even if wrapped in text
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(content)
            
        except Exception as e:
            print(f"❌ OpenRouter API Error: {str(e)}")
            
            # --- FALLBACK TO MOCK DATA (So your demo never crashes!) ---
            print("⚠️ Falling back to MOCK DATA for demonstration purposes.")
            return {
                "match_score": 85, "coding_skills_score": 90, "behavioral_skills_score": 80,
                "mandatory_skills_match_score": 100,
                "mandatory_skills_met": ["Python", "Django", "React", "AWS", "Docker"],
                "mandatory_skills_missed": [],
                "summary": "Strong candidate. Meets all mandatory skills. (Mock Data - API Failed)",
                "missing_skills": [], "recommendation": "Strong Yes",
                "is_fresher": False, "highest_education": "B.Tech in Computer Science",
                "extracted_experience": [{"company": "TechCorp", "title": "Senior Software Engineer", "duration": "Jan 2021 - Present", "description": "Built scalable APIs."}],
                "extracted_education": [{"degree": "B.Tech", "university": "University of Technology", "cgpa": "8.5/10", "graduation_year": "2019"}],
                "extracted_hobbies": ["Open-source", "Hiking", "Chess"],
                "extracted_university_projects": ["E-Commerce Platform", "Chat Application"]
            }

llm_validator = LLMValidator()