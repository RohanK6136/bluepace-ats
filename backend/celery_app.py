import os
from celery import Celery

APP_ENV = os.getenv("APP_ENV", "development")
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL and APP_ENV not in {"development", "test"}:
    raise RuntimeError("REDIS_URL must be configured outside development and test environments")
REDIS_URL = REDIS_URL or "redis://localhost:6379/0"

celery_app = Celery(
    "bluepace_ats",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.services.queue_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
