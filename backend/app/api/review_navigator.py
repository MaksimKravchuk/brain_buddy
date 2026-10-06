"""HTTP routes of the review navigator (spec 020, contracts/http.md §7).

Mounted empty by slice PR-15 so slice PR-07 adds only its own routes here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["review"])
