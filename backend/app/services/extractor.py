import io
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

from app.services.document_intelligence import DocumentIntelligenceError, document_intelligence_service
from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES

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
    def _resume_date_tokens(value, current_month):
        """Return ordered (calendar-month index, precision) date tokens."""
        month_pattern = (
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        )
        date_pattern = re.compile(
            rf"(?P<current>\b(?:present|current|now)\b)"
            rf"|(?P<month_name>\b(?P<month_name_value>{month_pattern})\.?\s*[,/.-]?\s*['’]?(?P<month_name_year>(?:19|20)\d{{2}}|\d{{2}})\b)"
            r"|(?P<month_year>\b(?P<month_num>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<month_num_year>(?:19|20)\d{2})\b)"
            r"|(?P<year_month>\b(?P<year_month_year>(?:19|20)\d{2})\s*[/.-]\s*(?P<year_month_num>0?[1-9]|1[0-2])\b)"
            r"|(?P<year_only>\b(?:19|20)\d{2}\b)",
            re.IGNORECASE,
        )
        month_numbers = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        tokens = []

        for match in date_pattern.finditer(str(value or "")):
            if match.group("current"):
                tokens.append((current_month, "current"))
                continue

            if match.group("month_name"):
                year_value = int(match.group("month_name_year"))
                if year_value < 100:
                    year_value += 2000 if year_value < 50 else 1900
                month = month_numbers[match.group("month_name_value")[:3].lower()]
                tokens.append((year_value * 12 + month - 1, "month"))
                continue

            if match.group("month_year"):
                year_value = int(match.group("month_num_year"))
                month = int(match.group("month_num"))
                tokens.append((year_value * 12 + month - 1, "month"))
                continue

            if match.group("year_month"):
                year_value = int(match.group("year_month_year"))
                month = int(match.group("year_month_num"))
                tokens.append((year_value * 12 + month - 1, "month"))
                continue

            if match.group("year_only"):
                year_value = int(match.group("year_only"))
                tokens.append((year_value * 12, "year"))

        return tokens

    @staticmethod
    def _experience_years_from_entries(experience, as_of=None):
        """Estimate distinct employment months, avoiding double-counted overlaps.

        Explicit month-specific end dates are counted inclusively. Year-only and
        present/current end dates are treated as exclusive month boundaries,
        avoiding an extra month when the exact day is not available.
        """
        reference_date = as_of or datetime.now()
        current_month = reference_date.year * 12 + reference_date.month - 1
        intervals = []

        for item in experience or []:
            if not isinstance(item, dict):
                continue
            duration = str(item.get("duration") or "")
            tokens = DocumentExtractor._resume_date_tokens(duration, current_month)

            # A duration may contain more than one explicit range. Pair tokens
            # in document order and ignore incomplete or malformed pairs.
            for token_index in range(0, len(tokens) - 1, 2):
                start_month = tokens[token_index][0]
                end_month, end_precision = tokens[token_index + 1]

                if start_month > current_month or end_month < start_month:
                    continue

                if end_month > current_month:
                    end_month = current_month
                    end_precision = "current"
                if end_precision != "month":
                    end_month -= 1
                if end_month >= start_month:
                    intervals.append((start_month, end_month))

        if not intervals:
            return None

        # Merge overlapping or adjacent intervals so concurrent roles are not
        # counted twice in total professional experience.
        merged = []
        for start_month, end_month in sorted(intervals):
            if merged and start_month <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end_month)
            else:
                merged.append([start_month, end_month])

        total_months = sum(end - start + 1 for start, end in merged)
        return round(total_months / 12, 1) if total_months else None

    @staticmethod
    def _resume_document_validation(raw_text, parsed):
        """Return fast upload-level validation separate from job-fit scoring."""
        text_length = len((raw_text or "").strip())
        email = str(parsed.get("email") or "").strip()
        phone_digits = re.sub(r"\D", "", str(parsed.get("phone") or ""))

        checks = {
            "readable_content": text_length >= 120,
            "candidate_identity": bool(parsed.get("name") or email),
            "email_format": not email or bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email)),
            "phone_present": len(phone_digits) >= 8,
            "skills_present": bool(parsed.get("skills")),
            "experience_or_fresher": bool(parsed.get("experience")) or bool(parsed.get("is_fresher")),
            "education_or_projects": bool(parsed.get("education") or parsed.get("university_projects") or parsed.get("projects")),
        }

        resume_signals = sum(
            bool(value) for value in (
                email,
                phone_digits,
                parsed.get("skills"),
                parsed.get("experience"),
                parsed.get("education"),
                parsed.get("projects"),
                parsed.get("certifications"),
            )
        )
        checks["resume_content_signals"] = resume_signals >= 2

        errors = []
        warnings = []
        if not checks["readable_content"]:
            errors.append("The document contains too little readable text to validate as a resume.")
        if not checks["candidate_identity"]:
            errors.append("Candidate name or email could not be identified.")
        if not checks["resume_content_signals"]:
            errors.append("The document does not contain enough resume-specific content.")

        for key, message in (
            ("email_format", "The extracted email format should be reviewed."),
            ("phone_present", "A usable phone number was not detected."),
            ("skills_present", "No skills were detected."),
            ("education_or_projects", "No education or project evidence was detected."),
        ):
            if not checks[key]:
                warnings.append(message)

        points = sum(bool(value) for key, value in checks.items() if key != "resume_content_signals")
        total = len([key for key in checks if key != "resume_content_signals"])
        score = round(points / max(total, 1) * 100)
        if errors:
            status = "invalid"
        elif warnings:
            status = "needs_review"
        else:
            status = "valid"

        return {
            "status": status,
            "score": score,
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "message": (
                "Resume passed basic validation."
                if status == "valid"
                else "Resume extracted, but review the validation warnings before ATS sync."
                if status == "needs_review"
                else "Resume validation failed. Fix the upload/content and retry."
            ),
        }

    @staticmethod
    def _evidence_line_for_value(value, indexed_lines):
        """Find a source line containing a complete value, not an arbitrary substring."""
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if not normalized:
            return None

        candidates = [normalized]
        if re.match(r"^https?://", normalized, re.IGNORECASE):
            candidates.append(re.sub(r"^https?://(?:www\.)?", "", normalized, flags=re.IGNORECASE))
        elif re.match(r"^www\.", normalized, re.IGNORECASE):
            candidates.append(re.sub(r"^www\.", "", normalized, flags=re.IGNORECASE))

        for candidate in candidates:
            escaped = re.escape(candidate)
            if candidate[0].isalnum():
                escaped = r"(?<!\w)" + escaped
            if candidate[-1].isalnum():
                escaped += r"(?!\w)"
            for line, normalized_line in indexed_lines:
                searchable_line = re.sub(r"\s+", " ", normalized_line).strip()
                if re.search(escaped, searchable_line, re.IGNORECASE):
                    return line
        return None

    @staticmethod
    def _evidence_and_confidence(raw_text, parsed, source_line_locations=None):
        """
        Attach source snippets and extraction confidence without turning inference into fact.
        Confidence describes extraction evidence coverage, not candidate quality or probability.
        """
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        indexed_lines = [(line, line.casefold()) for line in lines]
        source_line_locations = source_line_locations or []
        evidence = []
        confidence = {}

        explicit_fields = {
            "name": 0.95, "email": 0.99, "phone": 0.97, "linkedin": 0.99,
            "github": 0.99, "notice_period": 0.95, "current_location": 0.94,
            "preferred_location": 0.94, "work_authorization": 0.94,
            "certifications": 0.88, "skills": 0.88, "education": 0.88,
            "experience": 0.88, "projects": 0.85,
        }
        for field, base_confidence in explicit_fields.items():
            value = parsed.get(field)
            if not value:
                continue
            values = value if isinstance(value, list) else [value]
            matched = []
            matched_locations = []
            matched_value_count = 0
            total_value_count = 0

            for item in values[:20]:
                if isinstance(item, dict):
                    # Long free-text descriptions are not reliable identity anchors.
                    search_values = [
                        str(component).strip()
                        for key, component in item.items()
                        if key not in {"description", "summary", "details"}
                        and component is not None
                        and str(component).strip()
                    ]
                else:
                    search_values = [str(item).strip()] if item is not None and str(item).strip() else []

                for search_value in search_values[:10]:
                    total_value_count += 1
                    line_match = DocumentExtractor._evidence_line_for_value(
                        search_value, indexed_lines
                    )
                    if line_match:
                        matched_value_count += 1
                        if line_match not in matched:
                            matched.append(line_match)
                        line_index = next(
                            (
                                index for index, (source_line, _lower_line) in enumerate(indexed_lines)
                                if source_line == line_match
                            ),
                            None,
                        )
                        if line_index is not None and line_index < len(source_line_locations):
                            location = source_line_locations[line_index]
                            if location and location not in matched_locations:
                                matched_locations.append(location)

            coverage = (
                matched_value_count / total_value_count
                if total_value_count
                else 0.0
            )
            if coverage >= 0.8:
                field_confidence = base_confidence
            elif coverage >= 0.5:
                field_confidence = max(base_confidence - 0.10, 0.5)
            elif coverage > 0:
                field_confidence = max(base_confidence - 0.20, 0.5)
            else:
                field_confidence = max(base_confidence - 0.25, 0.5)

            evidence.append({
                "field": field,
                "value": value,
                "source_lines": matched[:5],
                "source_locations": matched_locations[:10],
                "evidence_coverage": round(coverage, 3),
                "matched_value_count": matched_value_count,
                "total_value_count": total_value_count,
                "confidence": field_confidence,
            })
            confidence[field] = field_confidence

        if parsed.get("years_of_experience") is not None:
            calculated = DocumentExtractor._experience_years_from_entries(parsed.get("experience"))
            explicit = DocumentExtractor._extract_explicit_experience_years(raw_text)
            confidence["years_of_experience"] = 0.97 if explicit is not None else (0.84 if calculated is not None else 0.5)
            years_source_lines = []
            years_source_locations = []

            if explicit is not None:
                for line_index, line in enumerate(lines):
                    if re.search(r"years?|yrs?", line, re.IGNORECASE) and "experience" in line.lower():
                        years_source_lines.append(line)
                        if line_index < len(source_line_locations):
                            location = source_line_locations[line_index]
                            if location and location not in years_source_locations:
                                years_source_locations.append(location)
            else:
                # Date-derived totals should point back to the employment-duration
                # text that contributed to the calculation.
                for item in parsed.get("experience") or []:
                    if not isinstance(item, dict):
                        continue
                    duration = str(item.get("duration") or "").strip()
                    if not duration:
                        continue
                    line_match = DocumentExtractor._evidence_line_for_value(
                        duration, indexed_lines
                    )
                    if line_match and line_match not in years_source_lines:
                        years_source_lines.append(line_match)
                        line_index = next(
                            (
                                index for index, (source_line, _lower_line) in enumerate(indexed_lines)
                                if source_line == line_match
                            ),
                            None,
                        )
                        if line_index is not None and line_index < len(source_line_locations):
                            location = source_line_locations[line_index]
                            if location and location not in years_source_locations:
                                years_source_locations.append(location)

            evidence.append({
                "field": "years_of_experience",
                "value": parsed["years_of_experience"],
                "source_lines": years_source_lines[:3],
                "source_locations": years_source_locations[:10],
                "confidence": confidence["years_of_experience"],
                "derivation": "explicit_resume_statement" if explicit is not None else "employment_dates",
            })

        return evidence, confidence

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
    def _docx_container_segments(container, source_part="body", section_index=None):
        """Extract DOCX text blocks with stable paragraph/table locators."""
        segments = []
        paragraph_index = 0
        table_index = 0
        active_section = None

        for block in container.iter_inner_content():
            if hasattr(block, "rows"):
                table_index += 1
                for row_index, row in enumerate(block.rows, start=1):
                    cells = []
                    cell_indices = []
                    for cell_index, cell in enumerate(row.cells, start=1):
                        cell_text = (cell.text or "").strip()
                        if cell_text:
                            cells.append(cell_text)
                            cell_indices.append(cell_index)
                    if cells:
                        location = {
                            "source_type": "docx_table_row",
                            "part": source_part,
                            "table_index": table_index,
                            "row_index": row_index,
                            "cell_indices": cell_indices,
                        }
                        if section_index is not None:
                            location["section_index"] = section_index
                        if active_section:
                            location["section"] = active_section
                        segments.append({
                            "text": " | ".join(cells),
                            "location": location,
                        })
            else:
                paragraph_index += 1
                paragraph_text = (block.text or "").strip()
                if not paragraph_text:
                    continue

                style_name = getattr(getattr(block, "style", None), "name", "") or ""
                normalized_style = style_name.casefold()
                if normalized_style == "title" or normalized_style.startswith("heading"):
                    active_section = paragraph_text

                location = {
                    "source_type": "docx_paragraph",
                    "part": source_part,
                    "paragraph_index": paragraph_index,
                }
                if section_index is not None:
                    location["section_index"] = section_index
                if active_section:
                    location["section"] = active_section
                segments.append({
                    "text": paragraph_text,
                    "location": location,
                })

        return segments

    @staticmethod
    def _source_line_locations(source_segments):
        """Return one locator per non-empty line in the same order as assembled text."""
        locations = []
        for segment in source_segments or []:
            location = segment.get("location") or {}
            for line in str(segment.get("text") or "").splitlines():
                if line.strip():
                    locations.append(dict(location))
        return locations

    def extract_to_json(self, file_content: bytes, filename: str) -> dict:
        if len(file_content) > MAX_DOCUMENT_SIZE_BYTES:
            raise DocumentExtractionError("Document must be 5 MB or smaller.")

        source_segments = []
        raw_text = ""
        source_line_locations = []
        source_location_status = "unavailable"
        extraction_engine = None
        extraction_warning = None

        configured_engine = os.getenv("DOCUMENT_EXTRACTION_ENGINE", "legacy").strip().lower()
        fallback_engine = os.getenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "docling").strip().lower()

        # Resume Lab is optimized for normal text-based resumes: PDF/DOCX parsing
        # with pypdf/python-docx is much faster than initializing a document-
        # understanding model. Docling remains available as an explicit mode and
        # as a fallback for scanned/image-heavy files when no text is extracted.
        if configured_engine in {"docling", "document_intelligence"}:
            try:
                docling_result = document_intelligence_service.extract(file_content, filename)
                raw_text = docling_result.text.strip()
                extraction_engine = docling_result.engine
                source_line_locations = docling_result.source_line_locations
                source_location_status = (
                    "available" if any(source_line_locations) else "unavailable"
                )
            except DocumentIntelligenceError as error:
                extraction_warning = str(error)

        if not raw_text:
            try:
                if filename.lower().endswith(".pdf"):
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(file_content))
                    for page_number, page in enumerate(reader.pages, start=1):
                        page_text = page.extract_text()
                        if page_text:
                            source_segments.append({
                                "text": page_text,
                                "location": {
                                    "source_type": "pdf_page",
                                    "page_number": page_number,
                                },
                            })
                    extraction_engine = "pypdf"
                elif filename.lower().endswith(".docx"):
                    from docx import Document
                    doc = Document(io.BytesIO(file_content))
                    source_segments.extend(
                        self._docx_container_segments(doc, source_part="body")
                    )
                    for section_index, section in enumerate(doc.sections, start=1):
                        source_segments.extend(
                            self._docx_container_segments(
                                section.header,
                                source_part="header",
                                section_index=section_index,
                            )
                        )
                        source_segments.extend(
                            self._docx_container_segments(
                                section.footer,
                                source_part="footer",
                                section_index=section_index,
                            )
                        )
                    extraction_engine = "python-docx"
                else:
                    raise ValueError("Unsupported resume format")
            except Exception as e:
                raise DocumentExtractionError(f"Failed to extract text: {str(e)}") from e
            raw_text = "\n".join(
                str(segment.get("text") or "") for segment in source_segments
            ).strip()
            source_line_locations = self._source_line_locations(source_segments)
            source_location_status = (
                "available" if source_line_locations else "unavailable"
            )

        if not raw_text and fallback_engine in {"docling", "document_intelligence"}:
            try:
                docling_result = document_intelligence_service.extract(file_content, filename)
                raw_text = docling_result.text.strip()
                extraction_engine = docling_result.engine
                source_line_locations = docling_result.source_line_locations
                source_location_status = (
                    "available" if any(source_line_locations) else "unavailable"
                )
            except DocumentIntelligenceError as error:
                extraction_warning = str(error)

        if not raw_text:
            raise DocumentExtractionError(
                "No readable text was found. The document may be scanned or image-only. "
                "Try a text-based PDF/DOCX resume or use Docling extraction for OCR-heavy documents."
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
        parsed["resume_validation"] = self._resume_document_validation(raw_text, parsed)
        parsed["extraction_evidence"], parsed["extraction_confidence"] = self._evidence_and_confidence(
            raw_text, parsed, source_line_locations
        )
        parsed["document_source_location_status"] = source_location_status
        parsed["document_source_line_count"] = sum(
            1 for location in source_line_locations if location
        )
        parsed["resume_intelligence_version"] = 6
        parsed["raw_text_length"] = len(raw_text)
        parsed["raw_text"] = raw_text
        parsed["document_extraction_engine"] = extraction_engine or "unknown"
        if extraction_warning:
            parsed["document_extraction_warning"] = extraction_warning

        # Validate the structured payload before returning it. Extraction remains
        # deterministic by default; this step only normalizes shape and types.
        try:
            from app.schemas import ResumeData
            validated = ResumeData.model_validate(parsed).model_dump()
            validated["raw_text"] = raw_text
            parsed = {**parsed, **validated}
        except Exception as error:
            raise DocumentExtractionError(
                f"Structured resume validation failed: {error}"
            ) from error

        return parsed

extractor_service = DocumentExtractor()