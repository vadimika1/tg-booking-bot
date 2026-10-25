from app.api.routers.bookings import router as bookings_router
from app.api.routers.health import router as health_router
from app.api.routers.metrics import router as metrics_router
from app.api.routers.services import router as services_router
from app.api.routers.slots import router as slots_router

__all__ = [
    "bookings_router",
    "health_router",
    "metrics_router",
    "services_router",
    "slots_router",
]
