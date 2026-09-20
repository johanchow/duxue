"""Production ASGI entry point and composition root."""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

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
    @app.exception_handler(StaleDataError)
    async def stale_write(request: Request, error: StaleDataError):
        return JSONResponse(status_code=409, content={"detail": "数据已变化，请刷新后重试"})

    app.include_router(router)
    configure_observability(component=os.getenv("OTEL_SERVICE_COMPONENT", "api"), app=app, engine=engine)
    return app


app = create_app()

__all__ = ["app"]
