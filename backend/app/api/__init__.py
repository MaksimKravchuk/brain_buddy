"""FastAPI routers for Brain Buddy."""

from fastapi import APIRouter

from .routes import router as api_router
from .vnext_routes import router as vnext_router

__all__ = ["api_router", "APIRouter", "vnext_router"]
