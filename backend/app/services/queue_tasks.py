import base64
import os
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import ResumeProcessingJob

from celery_app import celery_app
from app.services.extractor import extractor_service
from app.services.llm_validator import llm_validator
from app.services.slm_service import slm_service


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
            with open(job.storage_path, "rb") as handle:
                file_content = handle.read()
            extracted = extractor_service.extract_to_json(file_content, job.filename)
            extracted = enrich_extracted_with_slm(extracted)

            # Keep queue results compact. The original uploaded file remains
            # available at storage_path; raw_text is intentionally not duplicated
            # into the jobs table.
            result_data = {key: value for key, value in extracted.items() if key != "raw_text"}
            job.result_data = result_data
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            try:
                os.unlink(job.storage_path)
            except OSError:
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
