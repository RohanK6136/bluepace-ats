import base64
import os
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import ResumeProcessingJob

from celery_app import celery_app
from app.services.extractor import extractor_service
from app.services.llm_validator import llm_validator
from app.services.slm_service import slm_service
from app.services.private_storage import private_storage


def validate_resume_structure(extracted: dict) -> dict:
    """Fast deterministic schema/quality validation for extracted resumes."""
    required = ("name", "email", "phone", "skills", "experience", "education")
    missing = [key for key in required if not extracted.get(key)]
    warnings = []
    if extracted.get("email") and "@" not in str(extracted["email"]):
        warnings.append("email_format")
    if extracted.get("skills") is not None and not isinstance(extracted.get("skills"), list):
        warnings.append("skills_not_list")
    if extracted.get("experience") is not None and not isinstance(extracted.get("experience"), list):
        warnings.append("experience_not_list")
    if extracted.get("education") is not None and not isinstance(extracted.get("education"), list):
        warnings.append("education_not_list")
    score = max(0, round((len(required) - len(missing)) / len(required) * 100))
    return {
        "status": "valid" if not missing and not warnings else "needs_review",
        "score": score,
        "missing_fields": missing,
        "warnings": warnings,
        "fields_present": [key for key in required if extracted.get(key)],
    }


def enrich_extracted_with_slm(extracted: dict) -> dict:
    if not slm_service.enabled:
        return extracted
    enrichment = slm_service.enrich_resume(extracted)
    if enrichment:
        enriched = dict(extracted)
        enriched["slm_enrichment"] = enrichment
        return enriched
    return extracted


@celery_app.task(name="ats.extract_resume_task")
def extract_resume_task(file_name: str, file_content_b64: str, content_type: str = "application/pdf"):
    file_content = base64.b64decode(file_content_b64)
    extracted = extractor_service.extract_to_json(file_content, file_name)
    return enrich_extracted_with_slm(extracted)


@celery_app.task(name="ats.validate_resume_task")
def validate_resume_task(resume_json: dict, job_description: str):
    return llm_validator.validate_resume(resume_json, job_description)


@celery_app.task(name="ats.enrich_resume_slm_task")
def enrich_resume_slm_task(resume_json: dict):
    enrichment = slm_service.enrich_resume(resume_json)
    return {"status": "success", "slm_enrichment": enrichment}




@celery_app.task(name="ats.process_resume_ingest_job", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_resume_ingest_job(self, job_id: int):
    with SessionLocal() as db:
        job = db.get(ResumeProcessingJob, job_id)
        if job is None:
            return {"status": "missing", "job_id": job_id}

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        db.commit()

        try:
            file_content = private_storage.read_bytes(job.storage_path)
            extracted = extractor_service.extract_to_json(file_content, job.filename)
            extracted = enrich_extracted_with_slm(extracted)

            # Keep queue results compact. The original uploaded file remains
            # available at storage_path; raw_text is intentionally not duplicated
            # into the jobs table.
            result_data = {key: value for key, value in extracted.items() if key != "raw_text"}
            result_data["structure_validation"] = validate_resume_structure(extracted)

            requested_jd = None
            requested_job_id = None
            if isinstance(job.result_data, dict):
                requested_jd = job.result_data.get("_job_description")
                requested_job_id = job.result_data.get("_job_id")
            if requested_jd:
                from app.main import build_resume_job_summary
                result_data["job_fit"] = build_resume_job_summary(extracted, requested_jd)

            # Turn completed Resume Lab uploads into reusable ATS records. When a
            # target job was selected, also create the Applied application so the
            # existing email templates, pipeline, and matching workflow receive
            # the same validated resume data.
            if not job.candidate_id:
                from app.models import Candidate, Application, Job
                from app.services.workflow import ensure_job_stages, queue_application_email
                from app.main import _stage_email

                candidate_email = str(extracted.get("email") or "").strip().lower()
                if candidate_email:
                    name_parts = str(extracted.get("name") or "Applicant Candidate").strip().split()
                    first_name = (name_parts[0] if name_parts else "Applicant")[:100]
                    last_name = (" ".join(name_parts[1:]) if len(name_parts) > 1 else "Candidate")[:100]
                    candidate = db.query(Candidate).filter(
                        Candidate.organization_id == job.organization_id,
                        Candidate.email == candidate_email,
                    ).first()
                    if candidate is None:
                        candidate = Candidate(
                            organization_id=job.organization_id,
                            created_by_id=job.created_by_id,
                            first_name=first_name,
                            last_name=last_name,
                            email=candidate_email[:320],
                            phone=str(extracted.get("phone") or "")[:50] or None,
                            linkedin_url=str(extracted.get("linkedin") or "")[:500] or None,
                            source="Resume Lab",
                        )
                        db.add(candidate)
                        db.flush()
                    job.candidate_id = candidate.id
                    candidate.resume_data = result_data
                    candidate.phone = str(extracted.get("phone") or candidate.phone or "")[:50] or None
                    candidate.linkedin_url = str(extracted.get("linkedin") or candidate.linkedin_url or "")[:500] or None
                    candidate.needs_review = result_data["structure_validation"]["status"] != "valid"

                    if requested_job_id:
                        target_job = db.get(Job, int(requested_job_id))
                        if target_job is not None and target_job.organization_id == job.organization_id and target_job.status == "open":
                            application = db.query(Application).filter(
                                Application.job_id == target_job.id,
                                Application.candidate_id == candidate.id,
                            ).first()
                            if application is None:
                                stages = ensure_job_stages(db, target_job)
                                application = Application(
                                    organization_id=job.organization_id,
                                    job_id=target_job.id,
                                    candidate_id=candidate.id,
                                    stage_id=stages["Applied"].id,
                                    status="active",
                                )
                                db.add(application)
                                db.flush()
                                subject, body = _stage_email(application, "Applied", db=db)
                                email_id = queue_application_email(db, application, subject, body)
                                job.application_id = application.id
                            else:
                                job.application_id = application.id

            job.result_data = result_data

            # Public applications create the candidate/application immediately.
            # Once extraction finishes, enrich that existing record and recompute
            # the deterministic job match without blocking the applicant request.
            if job.candidate_id:
                from app.models import Candidate, Application, CandidateJobMatch, Job
                from app.services.matching import matching_service

                candidate = db.get(Candidate, job.candidate_id)
                if candidate is not None:
                    candidate.resume_data = result_data
                    if not candidate.phone and extracted.get("phone"):
                        candidate.phone = str(extracted["phone"])[:50]
                    if not candidate.linkedin_url and extracted.get("linkedin"):
                        candidate.linkedin_url = str(extracted["linkedin"])[:500]

                    if job.application_id:
                        application = db.get(Application, job.application_id)
                    else:
                        application = None
                    if application is not None:
                        linked_job = db.get(Job, application.job_id)
                        if linked_job is not None:
                            score = matching_service.score_candidate(linked_job, candidate)
                            existing_match = db.query(CandidateJobMatch).filter(
                                CandidateJobMatch.job_id == linked_job.id,
                                CandidateJobMatch.candidate_id == candidate.id,
                            ).first()
                            if existing_match is None:
                                existing_match = CandidateJobMatch(
                                    organization_id=job.organization_id,
                                    job_id=linked_job.id,
                                    candidate_id=candidate.id,
                                )
                                db.add(existing_match)
                            existing_match.model_score = score["model_score"]
                            existing_match.score_breakdown = score["score_breakdown"]
                            existing_match.matched_skills = score["matched_skills"]
                            existing_match.skill_gaps = score["skill_gaps"]
                            existing_match.explanations = score["explanations"]
                            existing_match.semantic_mode = score["semantic_mode"]

            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            try:
                private_storage.delete(job.storage_path)
            except Exception:
                pass

            return {"status": "completed", "job_id": job.id}
        except Exception as error:
            job.status = "failed"
            job.error_message = str(error)[:4000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise


@celery_app.task(name="ats.process_resume_batch")
def process_resume_batch(items):
    results = []
    for item in items:
        extracted = extract_resume_task.run(
            file_name=item["file_name"],
            file_content_b64=item["file_content_b64"],
            content_type=item.get("content_type", "application/pdf"),
        )
        validation = validate_resume_task.run(
            resume_json=extracted,
            job_description=item["job_description"],
        )
        results.append({
            "file_name": item["file_name"],
            "extracted": extracted,
            "validation": validation,
        })
    return results
