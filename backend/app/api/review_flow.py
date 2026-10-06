"""HTTP routes of the guided review flow (spec 020, contracts/http.md §6).

Mounted empty by slice PR-15 so slice PR-11 adds only its own routes here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["review"])
