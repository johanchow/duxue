"""API router assembly.

Route modules are registered here so the ASGI bootstrap has one stable import
target.  Existing paths are intentionally unchanged during the structural
migration.
"""

from fastapi import APIRouter

from app.api.v1.routes import router as v1_router


router = APIRouter()
router.include_router(v1_router)

__all__ = ["router"]
