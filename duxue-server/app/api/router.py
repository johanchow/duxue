"""API router assembly.

Route modules are registered here so the ASGI bootstrap has one stable import
target.  Existing paths are intentionally unchanged during the structural
migration.
"""

from fastapi import APIRouter

from app.api.v1 import behavior, companion, device_ingestion, evaluation, identity, memory, planning, study, system


router = APIRouter()
for context_router in (
    system.router,
    identity.router,
    device_ingestion.router,
    planning.router,
    study.router,
    evaluation.router,
    memory.router,
    companion.router,
    behavior.router,
):
    router.include_router(context_router)

__all__ = ["router"]
