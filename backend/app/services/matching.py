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


MATCH_WEIGHTS = {
    "required_skill_coverage": 0.25,
    "preferred_skill_coverage": 0.10,
    "experience_alignment": 0.15,
    "education_alignment": 0.10,
    "location_alignment": 0.08,
    "work_mode_alignment": 0.07,
    "project_evidence": 0.10,
    "semantic_similarity": 0.15,
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
    def _skill_pattern(cls, value):
        escaped = re.escape(str(value or "").strip())
        # Allow sentence punctuation such as "React." while still avoiding
        # false matches inside dotted skill names such as "React.js".
        return r"(?<![\w+#.])" + escaped + r"(?![\w+#])(?:\.(?![A-Za-z]))?"
    
    @classmethod
    def _extract_skills(cls, text):
        found = []
        content = str(text or "")
        for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(cls._skill_pattern(alias), content, re.IGNORECASE) and canonical not in found:
                found.append(canonical)
        for skill in SKILL_CATALOG:
            if skill not in found and re.search(cls._skill_pattern(skill), content, re.IGNORECASE):
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
        """
        Decision-support match analysis. Scores describe alignment with job
        requirements; they are not hiring recommendations or candidate quality.
        """
        analysis = job.jd_analysis or self.analyze_job(job)
        profile = candidate.resume_data or {}

        def norm(value):
            return re.sub(r"\s+", " ", str(value or "").strip().casefold())

        def normalized_skills(values):
            return {norm(self.normalize_skill(v)): self.normalize_skill(v) for v in (values or []) if str(v).strip()}

        candidate_skills = normalized_skills(profile.get("skills"))
        required_skills = [self.normalize_skill(v) for v in analysis.get("required_skills", [])]
        preferred_skills = [self.normalize_skill(v) for v in analysis.get("preferred_skills", [])]

        matched_required = [s for s in required_skills if norm(s) in candidate_skills]
        matched_preferred = [s for s in preferred_skills if norm(s) in candidate_skills]
        skill_gaps = [s for s in required_skills if norm(s) not in candidate_skills]
        required_score = round(len(matched_required) / len(required_skills) * 100) if required_skills else 100
        preferred_score = round(len(matched_preferred) / len(preferred_skills) * 100) if preferred_skills else 100

        experience = profile.get("experience") or []
        minimum_years = analysis.get("minimum_experience_years")
        years = self._estimate_experience_years(experience)
        if analysis.get("fresher_allowed") and not experience:
            experience_score = 100
            experience_note = "Fresher eligibility is allowed by the job."
        elif minimum_years is not None:
            experience_score = 100 if minimum_years == 0 else round(min(100, years / minimum_years * 100))
            experience_note = f"Parsed experience: {years:g} years; stated minimum: {minimum_years:g} years."
        else:
            experience_score = 100 if experience else 50
            experience_note = "Work history is present." if experience else "Work history was not parsed."

        education_entries = profile.get("education") or []
        required_education = norm(analysis.get("education"))
        candidate_education = " ".join(
            " ".join(str(v) for v in item.values()) if isinstance(item, dict) else str(item)
            for item in education_entries
        )
        education_tokens = self._tokens(required_education)
        candidate_education_tokens = self._tokens(candidate_education)
        education_score = (
            round(len(education_tokens & candidate_education_tokens) / len(education_tokens) * 100)
            if education_tokens else (100 if education_entries else 50)
        )

        required_location = norm(analysis.get("location"))
        candidate_location = norm(profile.get("current_location") or profile.get("location"))
        preferred_location = norm(profile.get("preferred_location"))
        work_mode = norm(analysis.get("work_mode"))
        candidate_work_mode = norm(profile.get("work_mode") or profile.get("work_preference"))

        location_score = 100
        if required_location and required_location not in {"remote", "hybrid", "onsite"}:
            location_tokens = self._tokens(required_location)
            candidate_location_tokens = self._tokens(candidate_location)
            preferred_location_tokens = self._tokens(preferred_location)
            overlap = location_tokens & (candidate_location_tokens | preferred_location_tokens)
            if required_location in candidate_location or required_location in preferred_location:
                location_score = 100
            elif location_tokens and len(overlap) / len(location_tokens) >= 0.5:
                location_score = 75
            elif not candidate_location and not preferred_location:
                location_score = 50
            else:
                location_score = 0
        elif not required_location:
            location_score = 100

        if work_mode in {"remote", "hybrid", "onsite"}:
            if candidate_work_mode:
                work_mode_score = 100 if candidate_work_mode == work_mode else (50 if work_mode == "hybrid" or candidate_work_mode == "hybrid" else 0)
            elif work_mode == "remote":
                work_mode_score = 100
            else:
                work_mode_score = 50
        else:
            work_mode_score = 100

        candidate_text = self.candidate_embedding_text(candidate)
        if job.embedding and candidate.embedding:
            semantic_score = round((self.cosine_similarity(job.embedding, candidate.embedding) + 1) * 50)
            semantic_mode = "embedding"
        else:
            jd_tokens = self._tokens(self.job_embedding_text(job))
            candidate_tokens = self._tokens(candidate_text)
            semantic_score = round(len(jd_tokens & candidate_tokens) / len(jd_tokens) * 100) if jd_tokens else 0
            semantic_mode = "lexical_fallback"

        project_items = profile.get("projects") or []
        project_text = " ".join(
            " ".join(str(v) for v in item.values()) if isinstance(item, dict) else str(item)
            for item in project_items
        )
        project_tokens = self._tokens(project_text)
        project_skill_matches = [
            skill for skill in required_skills
            if skill.casefold() in project_text.casefold()
            or self._tokens(skill).issubset(project_tokens)
        ]
        project_evidence_score = (
            round(len(project_skill_matches) / len(required_skills) * 100)
            if required_skills else (100 if project_items else 50)
        )

        skill_score = round(required_score * 0.80 + preferred_score * 0.20)
        breakdown = {
            "required_skill_coverage": required_score,
            "preferred_skill_coverage": preferred_score,
            "skills": skill_score,
            "experience_alignment": experience_score,
            "experience": experience_score,
            "education_alignment": education_score,
            "education": education_score,
            "location_alignment": location_score,
            "location": location_score,
            "work_mode_alignment": work_mode_score,
            "project_evidence": project_evidence_score,
            "semantic_similarity": semantic_score,
            "semantic": semantic_score,
        }

        # Weights are transparent and intentionally sum to 100.
        weights = MATCH_WEIGHTS
        model_score = round(sum(breakdown[key] * weight for key, weight in weights.items()))

        explanations = []
        if matched_required:
            explanations.append("Required skills found: " + ", ".join(matched_required) + ".")
        if skill_gaps:
            explanations.append("Required skill gaps: " + ", ".join(skill_gaps) + ".")
        if preferred_skills:
            explanations.append(f"Preferred-skill coverage: {preferred_score}%.")
        explanations.append(experience_note)
        if required_education:
            explanations.append(
                f"Education alignment: {education_score}% based on parsed education text."
            )
        if required_location:
            explanations.append(
                "Location aligns with the job location."
                if location_score == 100
                else "Location alignment is incomplete or not established from the resume."
            )
        if work_mode in {"remote", "hybrid", "onsite"}:
            explanations.append(f"Work-mode alignment: {work_mode_score}%.")
        if project_items:
            explanations.append(f"Project evidence coverage for required-skill terms: {project_evidence_score}%.")
        if semantic_mode == "lexical_fallback":
            explanations.append("Semantic embeddings are unavailable; semantic similarity uses text overlap.")

        summary = candidate.cv_summary or self._fallback_candidate_summary(candidate)
        return {
            "model_score": max(0, min(100, model_score)),
            "score_breakdown": breakdown,
            "score_weights": weights,
            "matched_skills": list(dict.fromkeys(matched_required + matched_preferred)),
            "matched_required_skills": matched_required,
            "matched_preferred_skills": matched_preferred,
            "skill_gaps": skill_gaps,
            "experience_years": years,
            "required_experience_years": minimum_years,
            "project_evidence": {
                "project_count": len(project_items),
                "coverage": project_evidence_score,
                "matched_required_skills": project_skill_matches,
            },
            "explanations": explanations,
            "decision_support_only": True,
            "semantic_mode": semantic_mode,
            "cv_summary": summary,
        }

matching_service = CandidateMatcher()