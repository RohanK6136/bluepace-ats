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
    "mongo": "MongoDB", "mongodb": "MongoDB", "k8s": "Kubernetes", "python3": "Python",
    "fast api": "FastAPI", "restful api": "REST API", "rest api": "REST API",
    "ml": "Machine Learning",
}

PREFERRED_MARKERS = ("nice to have", "preferred", "bonus", "plus", "desirable")
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
    def normalize_skill(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip().casefold())
        return SKILL_ALIASES.get(cleaned, str(value or "").strip())

    @classmethod
    def _extract_skills(cls, text):
        found = []
        for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"(?<![\w+#.])" + re.escape(alias) + r"(?![\w+#.])", str(text or ""), re.IGNORECASE) and canonical not in found:
                found.append(canonical)
        for skill in SKILL_CATALOG:
            if skill not in found and re.search(r"(?<![\w+#.])" + re.escape(skill) + r"(?![\w+#.])", str(text or ""), re.IGNORECASE):
                found.append(skill)
        return found

    @staticmethod
    def _normalize_analysis(data, fallback):
        normalized = dict(fallback)
        if not isinstance(data, dict):
            return normalized
        for field in ("required_skills", "preferred_skills"):
            values = data.get(field)
            if isinstance(values, list):
                normalized[field] = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        for field in ("seniority", "location", "education"):
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                normalized[field] = value.strip().casefold() if field == "seniority" else value.strip()
        minimum = data.get("minimum_experience_years")
        if isinstance(minimum, (int, float)) and 0 <= minimum <= 60:
            normalized["minimum_experience_years"] = int(minimum)
        return normalized

    def parse_job_description(self, title: str, description: str, location: str | None = None, *, use_llm: bool = False):
        text = f"{title}\n{description}"
        lower_text = text.casefold()
        preferred_positions = [lower_text.find(marker) for marker in PREFERRED_MARKERS if lower_text.find(marker) >= 0]
        preferred_start = min(preferred_positions, default=len(text))
        required_skills = self._extract_skills(text[:preferred_start])
        preferred_skills = [skill for skill in self._extract_skills(text[preferred_start:]) if skill not in required_skills] if preferred_start < len(text) else []

        minimum_years = None
        maximum_years = None
        range_match = re.search(r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\+?\s*(?:years|yrs)\b", text, re.IGNORECASE)
        single_match = re.search(r"\b(?:at least|minimum of|min(?:imum)?|more than|over)?\s*(\d{1,2})\+?\s*(?:years|yrs)(?: of)? experience\b", text, re.IGNORECASE)
        if range_match:
            minimum_years, maximum_years = int(range_match.group(1)), int(range_match.group(2))
        elif single_match:
            minimum_years = int(single_match.group(1))

        seniority = "unspecified"
        for level, pattern in (
            ("principal", r"\bprincipal\b"), ("staff", r"\bstaff\b"), ("lead", r"\blead\b"),
            ("senior", r"\bsenior\b|\bsr\.?\b"), ("mid", r"\bmid[- ]level\b|\bintermediate\b"),
            ("junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bgraduate\b"), ("intern", r"\bintern(ship)?\b"),
        ):
            if re.search(pattern, lower_text):
                seniority = level
                break

        education_match = re.search(r"\b(?:bachelor(?:'s)?|master(?:'s)?|associate(?:'s)?|doctoral|doctorate|ph\.?d\.?|m\.?b\.?a\.?|b\.?s\.?|m\.?s\.?|degree)\b[^.\n]*", text, re.IGNORECASE)
        responsibilities = []
        in_responsibilities = False
        for line in str(description).splitlines():
            clean = re.sub(r"^[#*•\-\s]+", "", line).strip()
            if re.match(r"^(responsibilities|what you'll do|what you will do|key duties)\s*:??$", clean, re.IGNORECASE):
                in_responsibilities = True
                continue
            if in_responsibilities and re.match(r"^(requirements|qualifications|skills|preferred|education|experience|benefits|interview)\b", clean, re.IGNORECASE):
                break
            if in_responsibilities and clean:
                responsibilities.append(clean)
        interview_topics = []
        for line in str(description).splitlines():
            if re.search(r"interview|assessment|technical round|technical interview", line, re.IGNORECASE):
                interview_topics.extend(self._extract_skills(line))

        location_match = re.search(r"\b(?:based in|located in|location\s*[:=]|office in|work from|in)\s+(remote|hybrid|[A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+){0,2})", text)
        work_mode = "remote" if re.search(r"\b(remote|work from home|wfh|fully remote)\b", lower_text) else "hybrid" if re.search(r"\bhybrid\b", lower_text) else "onsite"
        return {
            "required_skills": list(dict.fromkeys(required_skills)),
            "preferred_skills": list(dict.fromkeys(preferred_skills)),
            "skill_normalization": {alias: canonical for alias, canonical in SKILL_ALIASES.items() if re.search(r"(?<![\w+#.])" + re.escape(alias) + r"(?![\w+#.])", text, re.IGNORECASE)},
            "seniority": seniority,
            "location": location or (location_match.group(1).strip() if location_match else None),
            "work_mode": work_mode,
            "education": education_match.group(0).strip() if education_match else None,
            "minimum_experience_years": minimum_years,
            "maximum_experience_years": maximum_years,
            "responsibilities": responsibilities[:20],
            "interview_topics": list(dict.fromkeys(interview_topics))[:20],
        }

    def analyze_job(self, job) -> dict:
        analysis = self.parse_job_description(job.title, job.description, job.location, use_llm=False)
        if job.required_skills:
            analysis["required_skills"] = list(dict.fromkeys(self.normalize_skill(v) for v in job.required_skills))
        if job.minimum_experience_years is not None:
            analysis["minimum_experience_years"] = job.minimum_experience_years
        analysis["fresher_allowed"] = job.fresher_allowed
        analysis["work_mode"] = job.work_mode or analysis.get("work_mode")
        if job.location:
            analysis["location"] = job.location
        return analysis

    def embed_texts(self, texts: list[str]) -> list[list[float] | None]:
        if not texts:
            return []
        if self.embedding_client is None:
            return [None] * len(texts)
        try:
            response = self.embedding_client.embeddings.create(
                model=os.getenv("MATCHING_EMBEDDING_MODEL", "text-embedding-3-small"),
                input=[text[:12000] for text in texts],
                dimensions=1536,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors = [list(item.embedding) for item in ordered]
            return [vector if len(vector) == 1536 else None for vector in vectors]
        except Exception:
            return [None] * len(texts)

    @staticmethod
    def job_embedding_text(job) -> str:
        analysis = job.jd_analysis or {}
        return "\n".join(
            [
                job.title,
                job.description,
                str(job.location or ""),
                "Required skills: " + ", ".join(analysis.get("required_skills", [])),
                "Preferred skills: " + ", ".join(analysis.get("preferred_skills", [])),
                "Seniority: " + str(analysis.get("seniority", "")),
                "Education: " + str(analysis.get("education", "")),
                "Minimum experience: " + str(analysis.get("minimum_experience_years", "")),
                "Freshers allowed: " + str(analysis.get("fresher_allowed", False)),
            ]
        )

    @staticmethod
    def candidate_embedding_text(candidate) -> str:
        data = candidate.resume_data or {}
        profile = {key: value for key, value in data.items() if key != "raw_text"}
        return f"{candidate.first_name} {candidate.last_name}\n{json.dumps(profile, ensure_ascii=True)}"

    @staticmethod
    def _fallback_candidate_summary(candidate) -> list[str]:
        data = candidate.resume_data or {}
        name = f"{candidate.first_name} {candidate.last_name}".strip()
        experiences = data.get("experience") or []
        education = data.get("education") or []
        skills = data.get("skills") or []
        bullets = [f"Candidate profile for {name or 'unnamed candidate'}. "]
        if experiences:
            first_experience = experiences[0]
            role = first_experience.get("title") or "Professional"
            company = first_experience.get("company")
            duration = first_experience.get("duration")
            details = " · ".join(value for value in (role, company, duration) if value)
            bullets.append(f"Experience includes {details}.")
        else:
            bullets.append("No parsed work experience is available in the resume profile.")
        if skills:
            bullets.append("Key skills: " + ", ".join(str(skill) for skill in skills[:8]) + ".")
        else:
            bullets.append("No skills have been parsed from the resume yet.")
        if education:
            first_education = education[0]
            details = " · ".join(
                str(first_education.get(field))
                for field in ("degree", "university", "graduation_year")
                if first_education.get(field)
            )
            bullets.append(f"Education: {details}.")
        else:
            bullets.append("No parsed education is available in the resume profile.")
        return bullets[:5]

    def summarize_candidates(self, candidates: list) -> None:
        pending = [candidate for candidate in candidates if not candidate.cv_summary]
        for start in range(0, len(pending), 10):
            batch = pending[start : start + 10]
            if self.llm_client is None:
                for candidate in batch:
                    candidate.cv_summary = self._fallback_candidate_summary(candidate)
                continue

            profiles = []
            for candidate in batch:
                profile = {
                    key: value
                    for key, value in (candidate.resume_data or {}).items()
                    if key not in {"raw_text", "email", "phone", "linkedin", "github"}
                }
                profiles.append({"candidate_id": candidate.id, "name": f"{candidate.first_name} {candidate.last_name}", "profile": profile})
            prompt = (
                "Write 3 to 5 concise, factual CV-summary bullets for each candidate. Do not infer facts. "
                "Return JSON as {\"summaries\":[{\"candidate_id\":1,\"bullets\":[\"...\"]}]}. "
                "Include every candidate_id exactly once.\n"
                + json.dumps(profiles, ensure_ascii=True)[:24000]
            )
            summaries = {}
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.chat_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=3000,
                )
                result = json.loads(response.choices[0].message.content or "{}")
                entries = result.get("summaries") if isinstance(result, dict) else None
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        bullets = entry.get("bullets")
                        if not isinstance(bullets, list):
                            continue
                        valid = [str(bullet).strip().lstrip("-• ") for bullet in bullets if str(bullet).strip()]
                        if 3 <= len(valid) <= 5:
                            summaries[entry.get("candidate_id")] = valid
            except Exception:
                summaries = {}
            for candidate in batch:
                candidate.cv_summary = summaries.get(candidate.id) or self._fallback_candidate_summary(candidate)

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return max(-1.0, min(1.0, dot_product / (left_norm * right_norm)))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9+#.]+", text.lower()) if token not in STOP_WORDS and len(token) > 1}

    @staticmethod
    def _estimate_experience_years(experience: list[dict]) -> float:
        total = 0.0
        current_year = __import__("datetime").datetime.now().year
        for item in experience:
            duration = str(item.get("duration") or "")
            years_value = re.search(r"(\d+(?:\.\d+)?)\s*(?:years|yrs)", duration, re.IGNORECASE)
            if years_value:
                total += float(years_value.group(1))
                continue
            year_range = re.search(r"((?:19|20)\d{2})\s*(?:-|to|–|—)\s*(present|current|(?:19|20)\d{2})", duration, re.IGNORECASE)
            if year_range:
                end_year = current_year if year_range.group(2).lower() in {"present", "current"} else int(year_range.group(2))
                total += max(0, end_year - int(year_range.group(1)))
        return total

    def score_candidate(self, job, candidate) -> dict:
        analysis = job.jd_analysis or self.analyze_job(job)
        profile = candidate.resume_data or {}
        candidate_skills = {str(skill).casefold(): str(skill) for skill in profile.get("skills", [])}
        required_skills = analysis.get("required_skills", [])
        preferred_skills = analysis.get("preferred_skills", [])
        matched_required = [skill for skill in required_skills if skill.casefold() in candidate_skills]
        matched_preferred = [skill for skill in preferred_skills if skill.casefold() in candidate_skills]
        skill_gaps = [skill for skill in required_skills if skill.casefold() not in candidate_skills]
        required_score = (len(matched_required) / len(required_skills) * 100) if required_skills else 100
        preferred_score = (len(matched_preferred) / len(preferred_skills) * 100) if preferred_skills else 100
        skill_score = round(required_score * 0.8 + preferred_score * 0.2)

        candidate_text = self.candidate_embedding_text(candidate)
        if job.embedding and candidate.embedding:
            semantic_score = round((self.cosine_similarity(job.embedding, candidate.embedding) + 1) * 50)
            semantic_mode = "embedding"
        else:
            jd_tokens = self._tokens(self.job_embedding_text(job))
            candidate_tokens = self._tokens(candidate_text)
            semantic_score = round(len(jd_tokens & candidate_tokens) / len(jd_tokens) * 100) if jd_tokens else 0
            semantic_mode = "lexical_fallback"

        experience = profile.get("experience") or []
        minimum_years = analysis.get("minimum_experience_years")
        if analysis.get("fresher_allowed") and not experience:
            experience_score = 100
        elif minimum_years is not None:
            years = self._estimate_experience_years(experience)
            experience_score = 100 if minimum_years == 0 else round(min(100, years / minimum_years * 100))
        else:
            experience_score = 100 if experience else 50

        education_entries = profile.get("education") or []
        required_education = str(analysis.get("education") or "").casefold()
        candidate_education = " ".join(str(item) for item in education_entries).casefold()
        education_score = (
            100 if required_education and any(token in candidate_education for token in self._tokens(required_education))
            else 0 if required_education
            else 100 if education_entries
            else 50
        )

        required_location = str(analysis.get("location") or "").strip().casefold()
        candidate_location = str(profile.get("location") or "").strip().casefold()
        location_score = (
            100 if not required_location or required_location in {"remote", "hybrid"} and not candidate_location
            else 100 if required_location in candidate_location
            else 50 if not candidate_location
            else 0
        )

        breakdown = {
            "skills": skill_score,
            "semantic": semantic_score,
            "experience": experience_score,
            "education": education_score,
            "location": location_score,
        }
        weighted_score = (
            skill_score * 0.30
            + semantic_score * 0.30
            + experience_score * 0.15
            + education_score * 0.10
            + location_score * 0.15
        )
        explanations = []
        if matched_required:
            explanations.append("Required skills matched: " + ", ".join(matched_required) + ".")
        if skill_gaps:
            explanations.append("Required skill gaps: " + ", ".join(skill_gaps) + ".")
        if experience:
            first_experience = experience[0]
            role = first_experience.get("title") or first_experience.get("company")
            if role:
                explanations.append(f"Parsed experience includes {role}.")
        elif analysis.get("fresher_allowed"):
            explanations.append("This role is open to freshers; lack of work history is not penalized.")
        if required_education:
            explanations.append(
                "Education requirement is represented in the parsed profile."
                if education_score == 100
                else "The parsed profile does not show the requested education."
            )
        if semantic_mode == "lexical_fallback":
            explanations.append("Semantic embeddings are unavailable; the semantic component uses text overlap.")
        summary = candidate.cv_summary or self._fallback_candidate_summary(candidate)
        return {
            "model_score": max(0, min(100, round(weighted_score))),
            "score_breakdown": breakdown,
            "matched_skills": list(dict.fromkeys(matched_required + matched_preferred)),
            "skill_gaps": skill_gaps,
            "explanations": explanations,
            "semantic_mode": semantic_mode,
            "cv_summary": summary,
        }


matching_service = CandidateMatcher()