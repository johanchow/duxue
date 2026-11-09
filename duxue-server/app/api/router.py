"""API router assembly.

Route modules are registered here so the ASGI bootstrap has one stable import
target.  Existing paths are intentionally unchanged during the structural
migration.
"""

from fastapi import APIRouter

from app.api.v1 import (
    agent_admin,
    behavior,
    companion,
    device_ingestion,
    evaluation,
    gateway_ingestion,
    identity,
    memory,
    planning,
    study,
    system,
    tutoring_evidence,
)

router = APIRouter()
for context_router in (
    system.router,
    agent_admin.router,
    identity.router,
    device_ingestion.router,
    gateway_ingestion.router,
    planning.router,
    study.router,
    evaluation.router,
    tutoring_evidence.router,
    memory.router,
    companion.router,
    behavior.router,
):
    router.include_router(context_router)

__all__ = ["router"]
