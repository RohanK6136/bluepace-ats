import os
import json
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
            print(f"✅ Received response from OpenRouter.")
            return json.loads(content)
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