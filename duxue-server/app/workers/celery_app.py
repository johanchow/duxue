"""Celery application for bounded, idempotent infrastructure jobs."""

from celery import Celery

from app.bootstrap.settings import settings


celery_app = Celery("duxue", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "consume-learning-fact-outbox": {
            "task": "duxue.consume_learning_fact_outbox",
            "schedule": 5.0,
        },
        "maintain-memory-lifecycle": {
            "task": "duxue.maintain_memory_lifecycle",
            "schedule": 24 * 60 * 60.0,
        },
    },
)
