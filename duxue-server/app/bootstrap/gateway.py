"""Composition root for gateway command ports and their concrete adapters."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.commands.gateway_ingestion import GatewayCommands
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.gateway_repository import SqlCaptureRepository
from app.infrastructure.storage.object_storage import camera_storage


def gateway_commands(db: Annotated[Session, Depends(get_db)]) -> GatewayCommands:
    return GatewayCommands(SqlCaptureRepository(db), camera_storage)
