from __future__ import annotations

from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from app.api.routers import (
    bookings_router,
    health_router,
    metrics_router,
    services_router,
    slots_router,
)
from app.infrastructure.config import get_settings
from app.infrastructure.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="TG Booking Bot API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.started_at = datetime.now(timezone.utc)

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(services_router)
    app.include_router(bookings_router)
    app.include_router(slots_router)

    return app


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
