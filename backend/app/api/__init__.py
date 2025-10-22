"""FastAPI routers for Brain Buddy."""

from fastapi import APIRouter

from .routes import router as api_router

__all__ = ["api_router", "APIRouter"]
