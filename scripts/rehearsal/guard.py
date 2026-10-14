"""Production guard for the automated Apple-pilot rehearsal (spec 026, S1).

Nothing here talks to the network; ``run.py`` calls these checks before and
while it drives a target. Every production condition is independent, and a
missing one refuses the run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

CONFIRM_ENV = "BB_REHEARSAL_CONFIRM_PROD"
PROD_HOSTS = frozenset({"brain-buddy-frontend.fly.dev"})
PROD_REQUEST_BUDGET = 300
# Paths (after the /api prefix is stripped) that the rehearsal never requests on
# production: paid-AI request routes, live verification and operator routes.
BLOCKED_PREFIXES = (
    "/verify-live",
    "/review/navigator",
    "/admin",
    "/tasks/title-completions",
    "/brain-dump-operations",
)


class GuardError(RuntimeError):
    """A rehearsal safety condition failed; the run must stop."""


def check_prod_preconditions(
    target: str, base_url: str, env: Mapping[str, str] | None = None
) -> str:
    """The production host, or ``GuardError`` when any static condition fails."""
    env = os.environ if env is None else env
    if target != "prod":
        raise GuardError("production requires --target prod")
    expected = sorted(PROD_HOSTS)
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or host not in PROD_HOSTS
        or parts.port
        not in (
            None,
            443,
        )
    ):
        raise GuardError(f"host is not on the allowlist {expected}")
    if env.get(CONFIRM_ENV) != host:
        raise GuardError(f"{CONFIRM_ENV} must equal the target host")
    return host


def check_identity(me_status: int, me_email: str | None, accepted: set[str]) -> None:
    """``/api/auth/me`` must answer 200 with the email of rehearsal account A or B."""
    if me_status != 200 or not me_email or me_email.lower() not in accepted:
        raise GuardError("session is not a configured rehearsal account")


def check_capabilities(status: int, body: object) -> None:
    """The sync capabilities endpoint must answer for the user with the flag on."""
    if (
        status != 200
        or not isinstance(body, dict)
        or body.get("scope_enabled") is not True
    ):
        raise GuardError("sync capabilities do not show the flag effective")


def is_blocked(path: str, api_prefix: str = "/api") -> bool:
    """Whether a production request to ``path`` is on the blocklist."""
    route = path.split("?", 1)[0]
    if route.startswith(api_prefix):
        route = route[len(api_prefix) :]
    return (
        any(
            route == prefix or route.startswith(prefix + "/")
            for prefix in BLOCKED_PREFIXES
        )
        or "verify-live" in route
    )


class RequestBudget:
    """Client-side request counter with a hard stop."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise GuardError(f"request budget of {self.limit} exhausted")
        self.used += 1
