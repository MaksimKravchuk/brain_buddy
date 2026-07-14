"""FastAPI routers for Brain Buddy."""

from fastapi import APIRouter

from .routes import router as api_router
from .tasks import router as task_router

api_router.include_router(task_router)

__all__ = ["api_router", "APIRouter"]
