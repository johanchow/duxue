"""Production ASGI entry point and composition root."""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

from app.api.router import router
from app.bootstrap.settings import settings
from app.infrastructure.ai import components
from app.infrastructure.observability.telemetry import configure_observability
from app.infrastructure.persistence.database import engine


def create_app() -> FastAPI:
    from app.infrastructure.security.gateway import credentials
    credentials()
    components.validate_overrides()
    app = FastAPI(title="读学 Server", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    @app.exception_handler(StaleDataError)
    async def stale_write(request: Request, error: StaleDataError):
        return JSONResponse(status_code=409, content={"detail": "数据已变化，请刷新后重试"})

    from uuid import uuid4

    from app.application.commands.gateway_ingestion import GatewayError
    from app.contexts.ingestion.domain.gateway import CaptureConflict

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, error: GatewayError):
        return JSONResponse(status_code=error.status, content={"error_code": error.code, "message": error.code, "request_id": str(uuid4())})

    @app.exception_handler(CaptureConflict)
    async def capture_conflict(request: Request, error: CaptureConflict):
        return JSONResponse(status_code=409, content={"error_code": "EVIDENCE_CONFLICT", "message": "capture identity conflicts with existing evidence", "request_id": str(uuid4())})

    from app.agent_specs.release_runtime import (
        AgentConfigurationUnavailable,
        close_runtime,
        start_runtime,
    )
    @app.exception_handler(AgentConfigurationUnavailable)
    async def agent_config_unavailable(request: Request, error: AgentConfigurationUnavailable):
        return JSONResponse(status_code=503, content={"detail": "Agent配置尚未加载，请稍后重试"})

    app.router.add_event_handler("startup", start_runtime)
    app.router.add_event_handler("shutdown", close_runtime)
    app.include_router(router)
    configure_observability(component=os.getenv("OTEL_SERVICE_COMPONENT", "api"), app=app, engine=engine)
    return app


app = create_app()

__all__ = ["app"]
