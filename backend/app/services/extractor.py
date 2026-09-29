import io
import re

class DocumentExtractor:
    def __init__(self):
        self.common_skills = [
            "Python", "Django", "React", "REST API", "FastAPI",
            "JavaScript", "SQL", "AWS", "Docker", "Next.js",
            "Tailwind", "PostgreSQL", "MongoDB", "Git", "Java",
            "C++", "Node.js", "Machine Learning", "TypeScript"
        ]

    def extract_to_json(self, file_content: bytes, filename: str) -> dict:
        raw_text = ""
        try:
            if filename.lower().endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_content))
                for page in reader.pages:
                    if page.extract_text(): raw_text += page.extract_text() + "\n"
            elif filename.lower().endswith(".docx"):
                from docx import Document
                doc = Document(io.BytesIO(file_content))
                for para in doc.paragraphs:
                    if para.text: raw_text += para.text + "\n"
            print(f"✅ Extraction successful. Length: {len(raw_text)}")
        except Exception as e:
            raise Exception(f"Failed to extract text: {str(e)}")

        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', raw_text)
        phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', raw_text)
        linkedin_match = re.search(r'linkedin\.com/in/[a-zA-Z0-9_-]+', raw_text)
        github_match = re.search(r'github\.com/[a-zA-Z0-9_-]+', raw_text)

        found_skills = [s for s in self.common_skills if re.search(r'\b' + re.escape(s) + r'\b', raw_text, re.IGNORECASE)]
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
        possible_name = next((line.lstrip('#').strip() for line in lines[:5] if "@" not in line and len(line) < 60 and not line.startswith("http")), None)

        return {
            "name": possible_name,
            "email": email_match.group(0) if email_match else None,
            "phone": phone_match.group(0) if phone_match else None,
            "linkedin": linkedin_match.group(0) if linkedin_match else None,
            "github": github_match.group(0) if github_match else None,
            "skills": sorted(list(set(found_skills))),
            "experience": [], "education": [], "hobbies": [], "university_projects": [],
            "highest_education": None, "is_fresher": False,
            "raw_text_length": len(raw_text), "raw_text": raw_text
        }

extractor_service = DocumentExtractor()