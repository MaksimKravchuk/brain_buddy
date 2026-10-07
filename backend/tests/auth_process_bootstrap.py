"""Spawn initializer without application imports or shared bootstrap side effects."""

from __future__ import annotations

import os
from pathlib import Path


def isolate_app_bootstrap(root: str) -> None:
    """Keep incidental app startup separate from a test's explicit shared store."""
    os.environ["BRAIN_BUDDY_DATA_DIR"] = str(Path(root) / str(os.getpid()))
