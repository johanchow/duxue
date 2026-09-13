"""Celery adapters; workers call application services, never ORM tables ad hoc."""

from .celery_app import celery_app
from app.infrastructure.persistence.database import SessionLocal
from app.application.commands.memory_worker import consume_pending_learning_facts, run_memory_maintenance


@celery_app.task(name="duxue.consume_learning_fact_outbox")
def consume_learning_fact_outbox() -> int:
    with SessionLocal() as db:
        return consume_pending_learning_facts(db)


@celery_app.task(name="duxue.maintain_memory_lifecycle")
def maintain_memory_lifecycle() -> dict[str, int]:
    with SessionLocal() as db:
        return run_memory_maintenance(db)
