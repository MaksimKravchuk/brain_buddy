"""FastAPI routers for Brain Buddy."""

from fastapi import APIRouter

from .brain_dump import router as brain_dump_router
from .routes import router as api_router

__all__ = ["api_router", "APIRouter", "brain_dump_router"]
