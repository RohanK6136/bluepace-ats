import io
import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class DocumentExtractor:
    def __init__(self):
        self.common_skills = [
            "Python", "Django", "React", "REST API", "FastAPI",
            "JavaScript", "SQL", "AWS", "Docker", "Next.js",
            "Tailwind", "PostgreSQL", "MongoDB", "Git", "Java",
            "C++", "Node.js", "Machine Learning", "TypeScript", "Kubernetes",
            "Redis", "GraphQL", "Figma", "Excel", "Go", "Rust", "C#",
        ]
        api_key = os.getenv("OPENROUTER_API_KEY")
        self.client = (
            OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
            if api_key
            else None
        )

    @staticmethod
    def _section(lines, heading_pattern, all_headings):
        start = None
        for index, line in enumerate(lines):
            normalized = line.strip().strip("#*- ").rstrip(":").strip().lower()
            if re.fullmatch(heading_pattern, normalized, flags=re.IGNORECASE):
                start = index + 1
                break
        if start is None:
            return []
        content = []
        for line in lines[start:]:
            normalized = line.strip().strip("#*- ").rstrip(":").strip().lower()
            if any(re.fullmatch(pattern, normalized, flags=re.IGNORECASE) for pattern in all_headings):
                break
            if line.strip():
                content.append(line.strip())
        return content

    @staticmethod
    def _fallback_experience(lines):
        headings = [
            r"experience", r"work experience", r"professional experience", r"employment history",
            r"education", r"skills", r"projects", r"certifications", r"hobbies",
        ]
        section = DocumentExtractor._section(lines, r"experience|work experience|professional experience|employment history", headings)
        entries = []
        current = None
        for line in section:
            parts = [part.strip(" -") for part in line.split("|") if part.strip(" -")]
            has_dates = bool(re.search(r"(?:19|20)\d{2}|present|current", line, re.IGNORECASE))
            is_entry = len(parts) >= 2 and (has_dates or not re.search(r"[.!?]$", line))
            if is_entry:
                if current:
                    entries.append(current)
                current = {
                    "title": parts[0],
                    "company": parts[1] if len(parts) > 1 else None,
                    "duration": parts[2] if len(parts) > 2 else None,
                    "description": "",
                }
            elif current:
                current["description"] = " ".join(filter(None, [current["description"], line]))
        if current:
            entries.append(current)
        return entries

    @staticmethod
    def _fallback_education(lines):
        headings = [
            r"experience", r"work experience", r"professional experience", r"employment history",
            r"education", r"skills", r"projects", r"certifications", r"hobbies",
        ]
        section = DocumentExtractor._section(lines, r"education|academic background", headings)
        entries = []
        degree_pattern = re.compile(
            r"\b(B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|B\.?Tech|M\.?Tech|Bachelor|Master|Ph\.?D\.?|MBA|Associate|Diploma)\b",
            re.IGNORECASE,
        )
        for line in section:
            parts = [part.strip(" -") for part in line.split("|") if part.strip(" -")]
            if len(parts) < 2 or not (degree_pattern.search(line) or re.search(r"(?:19|20)\d{2}", line)):
                continue
            year = re.search(r"(?:19|20)\d{2}", line)
            cgpa = re.search(r"(?:GPA|CGPA)\s*[:=]?\s*([\d.]+(?:\s*/\s*[\d.]+)?)", line, re.IGNORECASE)
            entries.append(
                {
                    "degree": parts[0],
                    "university": parts[1],
                    "cgpa": cgpa.group(1) if cgpa else None,
                    "graduation_year": year.group(0) if year else None,
                }
            )
        return entries

    def _fallback_parse(self, raw_text):
        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text)
        phone_match = re.search(r"\+?\d{0,2}[\s.-]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
        linkedin_match = re.search(r"linkedin\.com/in/[a-zA-Z0-9_-]+", raw_text, re.IGNORECASE)
        github_match = re.search(r"github\.com/[a-zA-Z0-9_-]+", raw_text, re.IGNORECASE)
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        possible_name = next(
            (
                line.lstrip("#").strip()
                for line in lines[:5]
                if "@" not in line and len(line) < 60 and not line.startswith("http")
            ),
            None,
        )
        skills = [
            skill
            for skill in self.common_skills
            if re.search(r"\b" + re.escape(skill) + r"\b", raw_text, re.IGNORECASE)
        ]
        experience = self._fallback_experience(lines)
        education = self._fallback_education(lines)
        return {
            "name": possible_name,
            "email": email_match.group(0) if email_match else None,
            "phone": phone_match.group(0).strip() if phone_match else None,
            "linkedin": linkedin_match.group(0) if linkedin_match else None,
            "github": github_match.group(0) if github_match else None,
            "skills": sorted(set(skills)),
            "experience": experience,
            "education": education,
            "hobbies": [],
            "university_projects": [],
            "highest_education": education[0]["degree"] if education else None,
            "is_fresher": not bool(experience),
        }

    def _llm_parse(self, raw_text):
        if self.client is None:
            return None
        prompt = f"""
Extract only information present in this resume. Do not infer missing facts.
Return a JSON object with name, email, phone, linkedin, github, skills (strings),
experience (objects with company, title, duration, description), education
(objects with degree, university, cgpa, graduation_year), hobbies,
university_projects, highest_education, and is_fresher.

Resume text:
{raw_text[:12000]}
"""
        try:
            response = self.client.chat.completions.create(
                model="qwen/qwen-2.5-72b-instruct",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500,
            )
            content = response.choices[0].message.content
            payload = json.loads(content or "")
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def extract_to_json(self, file_content: bytes, filename: str) -> dict:
        raw_text = ""
        try:
            if filename.lower().endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_content))
                for page in reader.pages:
                    if page.extract_text():
                        raw_text += page.extract_text() + "\n"
            elif filename.lower().endswith(".docx"):
                from docx import Document
                doc = Document(io.BytesIO(file_content))
                for para in doc.paragraphs:
                    if para.text:
                        raw_text += para.text + "\n"
            else:
                raise ValueError("Unsupported resume format")
        except Exception as e:
            raise Exception(f"Failed to extract text: {str(e)}")
        parsed = self._fallback_parse(raw_text)
        llm_data = self._llm_parse(raw_text)
        if llm_data:
            for field in ("name", "email", "phone", "linkedin", "github", "highest_education"):
                if llm_data.get(field):
                    parsed[field] = llm_data[field]
            for field in ("skills", "experience", "education", "hobbies", "university_projects"):
                if isinstance(llm_data.get(field), list) and llm_data[field]:
                    parsed[field] = llm_data[field]
            if isinstance(llm_data.get("is_fresher"), bool):
                parsed["is_fresher"] = llm_data["is_fresher"]
        parsed["raw_text_length"] = len(raw_text)
        parsed["raw_text"] = raw_text
        return parsed

extractor_service = DocumentExtractor()