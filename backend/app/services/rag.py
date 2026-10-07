import re
import traceback

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Application, Candidate, Job, RagChunk
from app.services.matching import matching_service


class RagService:
    CHUNK_SIZE = 1100
    CHUNK_OVERLAP = 180
    MAX_RETRIEVAL_CHUNKS = 5
    MAX_CONTEXT_CHARS = 14000
    INJECTION_PATTERNS = (
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
        r"system\s*:",
        r"assistant\s*:",
        r"developer\s*:",
        r"reveal\s+(?:the\s+)?system\s+prompt",
        r"follow\s+these\s+instructions",
        r"you\s+are\s+now\s+",
    )

    @staticmethod
    def _chunks(text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return []
        chunks = []
        start = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + RagService.CHUNK_SIZE)
            chunk = cleaned[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(cleaned):
                break
            start = max(end - RagService.CHUNK_OVERLAP, start + 1)
        return chunks

    @staticmethod
    def _candidate_texts(candidate: Candidate) -> list[tuple[str, str]]:
        data = candidate.resume_data or {}
        values: list[tuple[str, str]] = []

        skills = ", ".join(str(v) for v in data.get("skills") or [] if str(v).strip())
        if skills:
            values.append(("skills", f"Skills: {skills}"))

        for field in ("experience", "education", "projects", "university_projects"):
            items = data.get(field) or []
            if isinstance(items, list) and items:
                values.append((field, str(items)))

        for field in ("notice_period", "current_location", "preferred_location", "work_authorization"):
            value = data.get(field)
            if value:
                values.append((field, f"{field}: {value}"))

        raw_text = data.get("raw_text")
        if raw_text:
            values.append(("raw_text", str(raw_text)))
        return values

    @staticmethod
    def _job_texts(job: Job) -> list[tuple[str, str]]:
        analysis = job.jd_analysis or {}
        values = [("title", job.title), ("description", job.description)]
        required = ", ".join(str(v) for v in analysis.get("required_skills") or job.required_skills or [])
        preferred = ", ".join(str(v) for v in analysis.get("preferred_skills") or [])
        if required:
            values.append(("required_skills", f"Required skills: {required}"))
        if preferred:
            values.append(("preferred_skills", f"Preferred skills: {preferred}"))
        if analysis.get("responsibilities"):
            values.append(("responsibilities", str(analysis.get("responsibilities"))))
        if analysis.get("interview_topics"):
            values.append(("interview_topics", str(analysis.get("interview_topics"))))
        return values

    @classmethod
    def _scan_untrusted_text(cls, text: str) -> tuple[str, bool]:
        """Mark likely indirect-prompt-injection text without treating it as executable."""
        cleaned = str(text or "")
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return cleaned, True
        return cleaned, False

    @classmethod
    def prepare_context(cls, items: list[dict], limit: int = 5) -> tuple[list[dict], dict]:
        """Bound and annotate retrieved RAG context before it reaches an LLM."""
        selected = []
        seen = set()
        chars = 0
        flagged = 0
        for item in items[: max(1, min(limit, cls.MAX_RETRIEVAL_CHUNKS))]:
            key = (item.get("source_id"), item.get("field"), item.get("text"))
            if key in seen:
                continue
            seen.add(key)
            raw_text = item.get("text", "")
            safe_text, suspicious = cls._scan_untrusted_text(raw_text)
            remaining = cls.MAX_CONTEXT_CHARS - chars
            if remaining <= 0:
                break
            safe_text = safe_text[:remaining]
            selected.append({
                **item,
                "text": safe_text,
                "untrusted": True,
                "prompt_injection_suspected": suspicious,
            })
            chars += len(safe_text)
            flagged += int(suspicious)
        return selected, {
            "chunks": len(selected),
            "context_chars": chars,
            "prompt_injection_flags": flagged,
        }

    def index_candidate(self, candidate_id: int, organization_id: int) -> int:
        with SessionLocal() as db:
            candidate = db.scalar(select(Candidate).where(
                Candidate.id == candidate_id,
                Candidate.organization_id == organization_id,
            ))
            if candidate is None:
                return 0
            db.execute(delete(RagChunk).where(
                RagChunk.organization_id == organization_id,
                RagChunk.source_type == "candidate",
                RagChunk.source_id == candidate.id,
            ))
            records = []
            for field, text in self._candidate_texts(candidate):
                for chunk_index, chunk in enumerate(self._chunks(text)):
                    records.append((field, chunk_index, chunk))
            vectors = matching_service.embed_texts([item[2] for item in records]) if records else []
            created = 0
            for index, (field, chunk_index, content) in enumerate(records):
                vector = vectors[index] if index < len(vectors) else None
                db.add(RagChunk(
                    organization_id=organization_id,
                    source_type="candidate",
                    source_id=candidate.id,
                    application_id=None,
                    field=field,
                    chunk_index=chunk_index,
                    content=content,
                    embedding=vector,
                ))
                created += 1
            db.commit()
            return created

    def index_job(self, job_id: int, organization_id: int) -> int:
        with SessionLocal() as db:
            job = db.scalar(select(Job).where(
                Job.id == job_id,
                Job.organization_id == organization_id,
            ))
            if job is None:
                return 0
            db.execute(delete(RagChunk).where(
                RagChunk.organization_id == organization_id,
                RagChunk.source_type == "job",
                RagChunk.source_id == job.id,
            ))
            records = []
            for field, text in self._job_texts(job):
                for chunk_index, chunk in enumerate(self._chunks(text)):
                    records.append((field, chunk_index, chunk))
            vectors = matching_service.embed_texts([item[2] for item in records]) if records else []
            for index, (field, chunk_index, content) in enumerate(records):
                vector = vectors[index] if index < len(vectors) else None
                db.add(RagChunk(
                    organization_id=organization_id,
                    source_type="job",
                    source_id=job.id,
                    application_id=None,
                    field=field,
                    chunk_index=chunk_index,
                    content=content,
                    embedding=vector,
                ))
            db.commit()
            return len(records)

    def ensure_application_index(self, application_id: int, organization_id: int, db=None) -> dict:
        """Ensure application RAG sources exist without escaping the caller's session.

        A caller-provided SQLAlchemy session is preferred so request handlers and
        tests observe the same transaction/connection. The legacy SessionLocal
        fallback keeps background callers compatible.
        """
        owns_session = db is None
        session = db or SessionLocal()
        try:
            application = session.scalar(
                select(Application).where(
                    Application.id == application_id,
                    Application.organization_id == organization_id,
                )
            )
            if application is None:
                return {"candidate_chunks": 0, "job_chunks": 0}
            candidate_ready = session.scalar(select(RagChunk.id).where(
                RagChunk.organization_id == organization_id,
                RagChunk.source_type == "candidate",
                RagChunk.source_id == application.candidate_id,
            ).limit(1))
            job_ready = session.scalar(select(RagChunk.id).where(
                RagChunk.organization_id == organization_id,
                RagChunk.source_type == "job",
                RagChunk.source_id == application.job_id,
            ).limit(1))
            candidate_id = application.candidate_id
            job_id = application.job_id

            result = {"candidate_chunks": 0, "job_chunks": 0}
        finally:
            if owns_session:
                session.close()

        if candidate_ready is None:
            try:
                result["candidate_chunks"] = self.index_candidate(candidate_id, organization_id)
            except Exception:
                traceback.print_exc()
        if job_ready is None:
            try:
                result["job_chunks"] = self.index_job(job_id, organization_id)
            except Exception:
                traceback.print_exc()
        return result

    def retrieve_for_application(self, db, application_id: int, organization_id: int, query: str, limit: int = 8) -> list[dict]:
        candidate = db.scalar(select(Application.candidate_id).where(
            Application.id == application_id,
            Application.organization_id == organization_id,
        ))
        job = db.scalar(select(Application.job_id).where(
            Application.id == application_id,
            Application.organization_id == organization_id,
        ))
        if candidate is None or job is None:
            return []

        query_vector = matching_service.embed_texts([query])[0]
        base = select(RagChunk).where(
            RagChunk.organization_id == organization_id,
            ((RagChunk.source_type == "candidate") & (RagChunk.source_id == candidate))
            | ((RagChunk.source_type == "job") & (RagChunk.source_id == job)),
        )

        if query_vector is not None and db.bind.dialect.name == "postgresql":
            candidate_terms = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", query.casefold()))
            rows = db.execute(
                select(
                    RagChunk,
                    (1 - RagChunk.embedding.cosine_distance(query_vector)).label("similarity"),
                )
                .where(
                    RagChunk.organization_id == organization_id,
                    RagChunk.embedding.is_not(None),
                    (
                        ((RagChunk.source_type == "candidate") & (RagChunk.source_id == candidate))
                        | ((RagChunk.source_type == "job") & (RagChunk.source_id == job))
                    ),
                )
                .order_by(RagChunk.embedding.cosine_distance(query_vector))
                .limit(min(limit * 3, 24))
            ).all()

            # Hybrid retrieval: semantic similarity finds related passages, then
            # a lightweight lexical boost keeps exact requested skills/names visible.
            reranked = []
            for index, (chunk, similarity) in enumerate(rows):
                tokens = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", chunk.content.casefold()))
                overlap = len(candidate_terms & tokens) / max(len(candidate_terms), 1)
                hybrid_score = (float(similarity) * 0.82) + (overlap * 0.18)
                reranked.append((hybrid_score, -index, chunk, float(similarity)))
            reranked.sort(key=lambda item: (item[0], item[1]), reverse=True)

            return [
                {
                    "source_id": "RESUME" if chunk.source_type == "candidate" else "JD",
                    "label": "Parsed resume" if chunk.source_type == "candidate" else "Job description",
                    "field": chunk.field,
                    "text": chunk.content,
                    "similarity": round(float(similarity) * 100, 1),
                    "hybrid_score": round(float(hybrid_score) * 100, 1),
                    "retrieval_mode": "hybrid_embedding_lexical",
                }
                for hybrid_score, _, chunk, similarity in reranked[:limit]
            ]

        terms = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", query.casefold()))
        rows = db.scalars(base.limit(200)).all()
        ranked = []
        for index, chunk in enumerate(rows):
            tokens = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", chunk.content.casefold()))
            overlap = len(terms & tokens) / max(len(terms), 1)
            ranked.append((overlap, -index, chunk))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            {
                "source_id": "RESUME" if chunk.source_type == "candidate" else "JD",
                "label": "Parsed resume" if chunk.source_type == "candidate" else "Job description",
                "field": chunk.field,
                "text": chunk.content,
                "similarity": round(float(score) * 100, 1),
                "retrieval_mode": "lexical_fallback",
            }
            for score, _, chunk in ranked[:limit]
            if score > 0
        ]


rag_service = RagService()
