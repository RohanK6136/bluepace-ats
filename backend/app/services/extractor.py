import io
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class DocumentExtractionError(ValueError):
    pass


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
            OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                timeout=8.0,
                max_retries=0,
            )
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

    @staticmethod
    def _fallback_projects(lines):
        headings = [
            r"projects", r"academic projects", r"university projects",
            r"personal projects", r"key projects", r"project experience",
        ]
        all_headings = [
            r"experience", r"work experience", r"professional experience",
            r"employment history", r"education", r"skills", r"projects",
            r"academic projects", r"university projects", r"personal projects",
            r"key projects", r"project experience", r"certifications", r"hobbies",
        ]
        for pattern in headings:
            section = DocumentExtractor._section(lines, pattern, all_headings)
            if section:
                return [line.strip(" -•") for line in section if line.strip(" -•")][:20]
        return []

    def _fallback_parse(self, raw_text):
        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text)
        phone_match = re.search(r"\+?\d{0,2}[\s.-]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
        linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9._-]+", raw_text, re.IGNORECASE)
        github_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9._-]+", raw_text, re.IGNORECASE)
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
        projects = self._fallback_projects(lines)
        return {
            "name": possible_name,
            "email": email_match.group(0) if email_match else None,
            "phone": phone_match.group(0).strip() if phone_match else None,
            "linkedin": self._normalize_url(linkedin_match.group(0)) if linkedin_match else None,
            "github": self._normalize_url(github_match.group(0)) if github_match else None,
            "skills": sorted(set(skills)),
            "experience": experience,
            "education": education,
            "hobbies": [],
            "university_projects": projects,
            "projects": projects,
            "certifications": self._extract_certifications(lines) or self._extract_inline_list(raw_text, ["certifications", "certification", "licenses", "license"]),
            "years_of_experience": self._extract_explicit_experience_years(raw_text) or self._experience_years_from_entries(experience),
            "companies": list(dict.fromkeys(str(item.get("company")).strip() for item in experience if isinstance(item, dict) and item.get("company"))),
            "job_titles": list(dict.fromkeys(str(item.get("title")).strip() for item in experience if isinstance(item, dict) and item.get("title"))),
            "current_location": self._extract_location(raw_text),
            "preferred_location": self._extract_preferred_location(raw_text),
            "notice_period": self._extract_notice_period(raw_text),
            "work_authorization": self._extract_work_authorization(raw_text),
            "highest_education": education[0]["degree"] if education else None,
            "is_fresher": not bool(experience),
        }

    @staticmethod
    def _extract_certifications(lines):
        headings = [r"certifications?", r"licenses?", r"professional certifications?"]
        all_headings = [
            r"experience", r"work experience", r"professional experience", r"employment history",
            r"education", r"skills", r"projects", r"academic projects", r"university projects",
            r"personal projects", r"key projects", r"project experience", r"certifications?",
            r"licenses?", r"hobbies", r"summary", r"profile",
        ]
        for pattern in headings:
            section = DocumentExtractor._section(lines, pattern, all_headings)
            if section:
                return [re.sub(r"^[•*\-]\s*", "", line).strip() for line in section if line.strip()][:30]
        return []

    @staticmethod
    def _normalize_url(value):
        value = re.sub(r"\s+", "", str(value or "")).strip()
        if not value:
            return None
        return value if re.match(r"^https?://", value, re.IGNORECASE) else "https://" + value

    @staticmethod
    def _extract_inline_list(raw_text, labels):
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})\s*[:\-]\s*([^\n]+)", raw_text, re.IGNORECASE)
        if not match:
            return []
        return [item.strip(" •*,-") for item in re.split(r"[,;|]", match.group(1)) if item.strip(" •*,-")][:30]

    @staticmethod
    def _extract_location(raw_text):
        patterns = [
            r"(?:current\s+location|location|based\s+in|residing\s+in)\s*[:\-]\s*([^\n|]{2,100})",
            r"(?:address|present\s+address)\s*[:\-]\s*([^\n|]{2,150})",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ,.-")
                if value:
                    return value
        return None

    @staticmethod
    def _extract_preferred_location(raw_text):
        patterns = [
            r"(?:preferred\s+location|preferred\s+locations|willing\s+to\s+relocate|relocation\s+preference)\s*[:\-]\s*([^\n|]{2,150})",
            r"(?:open\s+to\s+relocation|relocate\s+to)\s*[:\-]?\s*([^\n|]{2,150})",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ,.-")
                if value:
                    return value
        return None

    @staticmethod
    def _extract_notice_period(raw_text):
        patterns = [
            r"(?:notice\s+period|notice)\s*[:\-]?\s*(\d{1,3}\s*(?:days?|weeks?|months?)|immediate|serving\s+notice)",
            r"(\d{1,3})\s*(?:days?|weeks?|months?)\s*(?:notice\s+period)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()
        return None

    @staticmethod
    def _extract_work_authorization(raw_text):
        patterns = [
            r"(?:work\s+authorization|work\s+permit|visa\s+status|right\s+to\s+work|authorization\s+to\s+work)\s*[:\-]?\s*([^\n|]{2,120})",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ,.-")
                if value:
                    return value
        return None

    @staticmethod
    def _extract_explicit_experience_years(raw_text):
        patterns = [
            r"(?:years?|yrs?)\s+of\s+(?:professional\s+)?experience\s*[:\-]?\s*(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+)?experience",
        ]
        values = []
        for pattern in patterns:
            values.extend(float(v) for v in re.findall(pattern, raw_text, re.IGNORECASE))
        return max(values) if values else None

    @staticmethod
    def _experience_years_from_entries(experience):
        total_months = 0
        date_re = re.compile(r"(\d{4})\s*(?:-|–|to)\s*(\d{4}|present|current)", re.IGNORECASE)
        for item in experience or []:
            if not isinstance(item, dict):
                continue
            duration = str(item.get("duration") or "")
            match = date_re.search(duration)
            if not match:
                continue
            start, end = int(match.group(1)), match.group(2).lower()
            end_year = datetime_year = None
            if end in {"present", "current"}:
                from datetime import datetime
                end_year = datetime.now().year
            else:
                end_year = int(end)
            if end_year >= start:
                total_months += (end_year - start) * 12
        return round(total_months / 12, 1) if total_months else None

    @staticmethod
    def _resume_quality_flags(raw_text, parsed):
        missing = []
        optional_missing = []
        suspicious = []
        for key in ("email", "phone", "skills", "experience", "education"):
            if not parsed.get(key):
                missing.append(key)
        optional = {
            "linkedin": "LinkedIn", "github": "GitHub", "certifications": "certifications",
            "current_location": "current location", "preferred_location": "preferred location",
            "notice_period": "notice period", "work_authorization": "work authorization",
        }
        for key, label in optional.items():
            if not parsed.get(key):
                optional_missing.append(label)

        email = str(parsed.get("email") or "")
        if email and not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email):
            suspicious.append({"field": "email", "severity": "medium", "reason": "Extracted email does not match a standard email pattern.", "evidence": email})
        phone = str(parsed.get("phone") or "")
        if phone and len(re.sub(r"\D", "", phone)) < 8:
            suspicious.append({"field": "phone", "severity": "low", "reason": "Extracted phone number appears unusually short.", "evidence": phone})

        explicit = parsed.get("years_of_experience")
        calculated = DocumentExtractor._experience_years_from_entries(parsed.get("experience"))
        if explicit is not None and calculated is not None and abs(float(explicit) - float(calculated)) > 2:
            suspicious.append({"field": "years_of_experience", "severity": "medium", "reason": "Explicit experience duration differs materially from the employment dates detected.", "evidence": f"Explicit: {explicit}; date-based estimate: {calculated}"})

        current_year = datetime.now().year
        for item in parsed.get("education") or []:
            year = item.get("graduation_year") if isinstance(item, dict) else None
            if year:
                try:
                    if int(str(year)) > current_year + 2:
                        suspicious.append({"field": "education", "severity": "medium", "reason": "Graduation year is unusually far in the future; verify it.", "evidence": str(year)})
                except ValueError:
                    pass

        return {
            "missing_fields": missing,
            "optional_missing_fields": optional_missing,
            "suspicious_fields": suspicious,
            "disclaimer": "Review signals are based only on extracted resume text and are not definitive facts about the candidate.",
        }

    def _llm_parse(self, raw_text):
        if self.client is None:
            return None
        prompt = f"""
Extract only information present in this resume. Do not infer missing facts.
Return a JSON object with name, email, phone, linkedin, github, skills (strings),
years_of_experience, companies (strings), job_titles (strings), experience
(objects with company, title, duration, description), education
(objects with degree, university, cgpa, graduation_year), certifications (strings),
projects, university_projects, highest_education, notice_period, current_location,
preferred_location, work_authorization, and is_fresher. Extract only explicit
evidence from the resume; never infer missing facts. Use null or [] when absent.

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

    @staticmethod
    def _docx_container_text(container):
        lines = []
        for block in container.iter_inner_content():
            if hasattr(block, "rows"):
                for row in block.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        lines.append(" | ".join(cells))
            elif block.text.strip():
                lines.append(block.text.strip())
        return lines

    def extract_to_json(self, file_content: bytes, filename: str) -> dict:
        text_parts = []
        try:
            if filename.lower().endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_content))
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            elif filename.lower().endswith(".docx"):
                from docx import Document
                doc = Document(io.BytesIO(file_content))
                text_parts.extend(self._docx_container_text(doc))
                for section in doc.sections:
                    text_parts.extend(self._docx_container_text(section.header))
                    text_parts.extend(self._docx_container_text(section.footer))
            else:
                raise ValueError("Unsupported resume format")
        except Exception as e:
            raise DocumentExtractionError(f"Failed to extract text: {str(e)}") from e
        raw_text = "\n".join(text_parts).strip()
        if not raw_text:
            raise DocumentExtractionError(
                "No readable text was found. The document may be scanned or image-only; "
                "upload a text-based PDF or DOCX file."
            )
        parsed = self._fallback_parse(raw_text)
        llm_data = self._llm_parse(raw_text) if os.getenv("ENABLE_LLM_RESUME_ENRICHMENT", "false").lower() == "true" else None
        if llm_data:
            for field in ("name", "email", "phone", "linkedin", "github", "highest_education", "years_of_experience", "current_location", "preferred_location", "notice_period", "work_authorization"):
                if llm_data.get(field):
                    parsed[field] = llm_data[field]
            for field in ("skills", "experience", "education", "hobbies", "university_projects", "projects", "certifications", "companies", "job_titles"):
                if isinstance(llm_data.get(field), list) and llm_data[field]:
                    parsed[field] = llm_data[field]
            if isinstance(llm_data.get("is_fresher"), bool):
                parsed["is_fresher"] = llm_data["is_fresher"]
        for social_field in ("linkedin", "github"):
            if parsed.get(social_field):
                parsed[social_field] = self._normalize_url(parsed[social_field])
        if not parsed.get("projects"):
            parsed["projects"] = parsed.get("university_projects") or []
        if not parsed.get("companies"):
            parsed["companies"] = list(dict.fromkeys(str(item.get("company")).strip() for item in parsed.get("experience") or [] if isinstance(item, dict) and item.get("company")))
        if not parsed.get("job_titles"):
            parsed["job_titles"] = list(dict.fromkeys(str(item.get("title")).strip() for item in parsed.get("experience") or [] if isinstance(item, dict) and item.get("title")))
        if parsed.get("years_of_experience") is None:
            parsed["years_of_experience"] = self._experience_years_from_entries(parsed.get("experience"))
        parsed["resume_quality"] = self._resume_quality_flags(raw_text, parsed)
        parsed["resume_intelligence_version"] = 2
        parsed["raw_text_length"] = len(raw_text)
        parsed["raw_text"] = raw_text
        return parsed

extractor_service = DocumentExtractor()