"""FastAPI routers for Brain Buddy."""

from fastapi import APIRouter

from .agents import router as agent_router
from .review import router as review_router
from .review_flow import router as review_flow_router
from .review_navigator import router as review_navigator_router
from .routes import router as api_router
from .tasks import router as task_router

api_router.include_router(task_router)
# Spec 020: the three weekly-review routers, mounted together so the navigator
# (PR-07) and flow (PR-11) slices only add routes to their own files.
api_router.include_router(review_router)
api_router.include_router(review_navigator_router)
api_router.include_router(review_flow_router)
api_router.include_router(agent_router)

__all__ = ["api_router", "APIRouter"]
