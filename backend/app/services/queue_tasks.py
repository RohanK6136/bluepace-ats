import base64

from celery_app import celery_app
from app.services.extractor import extractor_service
from app.services.llm_validator import llm_validator


@celery_app.task(name="ats.extract_resume_task")
def extract_resume_task(file_name: str, file_content_b64: str, content_type: str = "application/pdf"):
    file_content = base64.b64decode(file_content_b64)
    return extractor_service.extract_to_json(file_content, file_name)


@celery_app.task(name="ats.validate_resume_task")
def validate_resume_task(resume_json: dict, job_description: str):
    return llm_validator.validate_resume(resume_json, job_description)


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
