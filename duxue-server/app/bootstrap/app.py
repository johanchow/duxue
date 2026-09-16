"""Production ASGI entry point and composition root."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.bootstrap.settings import settings
from app.infrastructure.observability.telemetry import configure_observability
from app.infrastructure.persistence.database import engine


def create_app() -> FastAPI:
    app = FastAPI(title="读学 Server", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    configure_observability(component=os.getenv("OTEL_SERVICE_COMPONENT", "api"), app=app, engine=engine)
    return app


app = create_app()

__all__ = ["app"]
