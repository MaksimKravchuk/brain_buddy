"""Brain Buddy backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the web app explicitly; library imports must not initialize storage."""
    from .main import create_app as factory  # noqa: PLC0415 - defer app startup

    return factory()


__all__ = ["create_app"]
