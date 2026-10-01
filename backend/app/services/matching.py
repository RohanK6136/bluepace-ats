import json
import math
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SKILL_CATALOG = (
    "Python", "Django", "React", "REST API", "FastAPI", "JavaScript", "SQL",
    "AWS", "Docker", "Next.js", "Tailwind", "PostgreSQL", "MongoDB", "Git",
    "Java", "C++", "Node.js", "Machine Learning", "TypeScript", "Kubernetes",
    "Redis", "GraphQL", "Figma", "Excel", "Go", "Rust", "C#", "Azure", "GCP",
    "Terraform", "Linux", "Salesforce", "Tableau", "Power BI", "Swift", "Kotlin",
)
SKILL_ALIASES = {
    "reactjs": "React", "react.js": "React", "react js": "React",
    "nodejs": "Node.js", "node.js": "Node.js", "node js": "Node.js",
    "nextjs": "Next.js", "next.js": "Next.js", "next js": "Next.js",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "postgre sql": "PostgreSQL",
    "mongo": "MongoDB", "mongodb": "MongoDB", "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "python3": "Python", "fast api": "FastAPI", "fastapi": "FastAPI",
    "restful api": "REST API", "rest api": "REST API", "ml": "Machine Learning",
}
PREFERRED_MARKERS = ("nice to have", "preferred", "bonus", "plus", "desirable", "good to have")
SECTION_HEADINGS = {
    "responsibilities": ("responsibilities", "what you'll do", "what you will do", "role responsibilities", "key duties"),
    "interview_topics": ("interview", "interview process", "technical interview", "what we assess", "assessment"),
}
STOP_WORDS = {
    "and", "the", "for", "with", "from", "that", "this", "have", "has", "are",
    "will", "you", "your", "our", "their", "years", "year", "experience", "work",
    "ability", "strong", "role", "team", "skills", "skill", "required", "preferred",
}


class CandidateMatcher:
    def __init__(self):
        load_dotenv()
        openai_key = os.getenv("OPENAI_API_KEY")
        router_key = os.getenv("OPENROUTER_API_KEY")
        self.embedding_client = OpenAI(api_key=openai_key) if openai_key else None
        if router_key:
            self.llm_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=router_key)
            self.chat_model = os.getenv("MATCHING_CHAT_MODEL", "qwen/qwen-2.5-72b-instruct")
        elif openai_key:
            self.llm_client = OpenAI(api_key=openai_key)
            self.chat_model = os.getenv("MATCHING_CHAT_MODEL", "gpt-4o-mini")
        else:
            self.llm_client = None
            self.chat_model = None

    @staticmethod
    def normalize_skill(skill: str) -> str:
        value = re.sub(r"[^a-z0-9+#.]+", " ", str(skill or "").casefold()).strip()
        aliases = {
            "reactjs": "React", "react js": "React", "react.js": "React",
            "nodejs": "Node.js", "node js": "Node.js", "node.js": "Node.js",
            "nextjs": "Next.js", "next js": "Next.js", "next.js": "Next.js",
            "typescript": "TypeScript", "ts": "TypeScript",
            "javascript": "JavaScript", "js": "JavaScript",
            "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
            "mongo": "MongoDB", "mongodb": "MongoDB",
            "scikit learn": "scikit-learn", "scikit-learn": "scikit-learn",
            "machine learning": "Machine Learning", "ml": "Machine Learning",
            "artificial intelligence": "Artificial Intelligence", "ai": "Artificial Intelligence",
            "rest": "REST API", "rest api": "REST API",
            "fast api": "FastAPI", "fastapi": "FastAPI",
            "powerbi": "Power BI", "power bi": "Power BI",
        }
        return aliases.get(value, str(skill or "").strip())

    @classmethod
    def normalize_skills(cls, skills):
        result = []
        seen = set()
        for skill in skills or []:
            normalized = cls.normalize_skill(skill)
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result

    @staticmethod
    def normalize_skill(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip().casefold())
        return SKILL_ALIASES.get(cleaned, str(value or "").strip())

    @classmethod
    def _extract_skills(cls, text):
        found = []
        content = str(text or "")
        for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"(?<![\w+#.])" + re.escape(alias) + r"(?![\w+#.])", content, re.IGNORECASE) and canonical not in found:
                found.append(canonical)
        for skill in SKILL_CATALOG:
            if skill not in found and re.search(r"(?<![\w+#.])" + re.escape(skill) + r"(?![\w+#.])", content, re.IGNORECASE):
                found.append(skill)
        return found

    @staticmethod
    def _section(text: str, headings: tuple[str, ...]) -> str:
        lines, collecting, chunks = str(text or "").splitlines(), False, []
        stop = ("requirements", "qualifications", "skills", "preferred", "nice to have", "education", "experience", "benefits", "about us", "about the role", "responsibilities", "interview", "what you'll do")
        for line in lines:
            clean = re.sub(r"^[#*\-\s]+", "", line).strip().casefold()
            if clean and any(clean == h or clean.startswith(h + ":") for h in headings):
                collecting = True; continue
            if collecting and clean and any(clean == h or clean.startswith(h + ":") for h in stop):
                break
            if collecting and line.strip(): chunks.append(line.strip())
        return "\n".join(chunks)

    @staticmethod
    def _extract_experience(text: str):
        content = str(text or "")
        ranges = re.findall(r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\+?\s*(?:years|yrs)\b", content, re.IGNORECASE)
        singles = re.findall(r"\b(?:at least|minimum of|min(?:imum)?|more than|over)?\s*(\d{1,2})\+?\s*(?:years|yrs)(?: of)? experience\b", content, re.IGNORECASE)
        return (int(singles[0]) if singles else int(ranges[0][0]) if ranges else None, int(ranges[0][1]) if ranges else None)

    @staticmethod
    def _infer_seniority(text: str) -> str:
        lower = str(text or "").casefold()
        for level, pattern in (("principal", r"\bprincipal\b"), ("staff", r"\bstaff\b"), ("lead", r"\blead\b"), ("senior", r"\bsenior\b|\bsr\.?\b"), ("mid", r"\bmid[- ]level\b|\bintermediate\b"), ("junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bgraduate\b"), ("intern", r"\bintern(ship)?\b")):
            if re.search(pattern, lower): return level
        return "unspecified"
    def parse_job_description(self, title: str, description: str, location: str | None = None, *, use_llm: bool = False):
        text = f"{title}\n{description}"
        lower = text.casefold()
        positions = [lower.find(marker) for marker in PREFERRED_MARKERS if lower.find(marker) >= 0]
        split_at = min(positions, default=len(text))
        required_skills = self._extract_skills(text[:split_at])
        preferred_skills = [s for s in self._extract_skills(text[split_at:]) if s not in required_skills] if split_at < len(text) else []
        minimum, maximum = self._extract_experience(text)
        education_match = re.search(r"\b(?:bachelor(?:'s)?|master(?:'s)?|associate(?:'s)?|doctoral|doctorate|ph\.?d\.?|m\.?b\.?a\.?|b\.?s\.?|m\.?s\.?|degree)\b[^.\n]*", text, re.IGNORECASE)
        responsibilities_text = self._section(description, SECTION_HEADINGS["responsibilities"])
        interview_text = self._section(description, SECTION_HEADINGS["interview_topics"])
        responsibilities = [re.sub(r"^[•*\-]+\s*", "", line).strip() for line in responsibilities_text.splitlines() if line.strip()]
        interview_topics = self._extract_skills(interview_text)
        location_match = re.search(r"\b(?:based in|located in|location\s*[:=]|office in|work from)\s+(remote|hybrid|[A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+){0,2})", text)
        work_mode = "remote" if re.search(r"\b(remote|work from home|wfh|fully remote)\b", lower) else "hybrid" if re.search(r"\bhybrid\b", lower) else "onsite"
        return {
            "required_skills": list(dict.fromkeys(required_skills)),
            "preferred_skills": list(dict.fromkeys(preferred_skills)),
            "skill_normalization": {alias: canonical for alias, canonical in SKILL_ALIASES.items() if re.search(r"(?<![\w+#.])" + re.escape(alias) + r"(?![\w+#.])", text, re.IGNORECASE)},
            "seniority": self._infer_seniority(text),
            "location": location or (location_match.group(1).strip() if location_match else None),
            "work_mode": work_mode,
            "education": education_match.group(0).strip() if education_match else None,
            "minimum_experience_years": minimum,
            "maximum_experience_years": maximum,
            "responsibilities": responsibilities[:20],
            "interview_topics": interview_topics[:20],
        }
    def analyze_job(self, job) -> dict:
        analysis = self.parse_job_description(job.title, job.description, job.location, use_llm=False)
        if job.required_skills:
            analysis["required_skills"] = list(dict.fromkeys(self.normalize_skill(v) for v in job.required_skills))
        if job.minimum_experience_years is not None:
            analysis["minimum_experience_years"] = job.minimum_experience_years
        analysis["fresher_allowed"] = job.fresher_allowed
        analysis["work_mode"] = job.work_mode or analysis.get("work_mode")
        analysis["location"] = job.location or analysis.get("location")
        analysis["work_mode"] = job.work_mode or analysis.get("work_mode")
        if job.location:
            analysis["location"] = job.location
        return analysis
)