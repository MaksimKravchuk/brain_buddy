"""Owner-scoped exposure resolution for the CRT facade."""

from __future__ import annotations

from dataclasses import dataclass

from app.repositories.feature_flag import FlagMode
from app.schemas.auth import User
from app.services.feature_flag_service import FeatureFlagService


class CrtFeatureFlagUnavailableError(RuntimeError):
    """The runtime flag store cannot provide a trustworthy exposure decision."""


@dataclass(frozen=True, slots=True)
class CrtExposure:
    """The content-free exposure decision for one authenticated user."""

    effective: bool


class CrtExposureService:
    """Resolve CRT exposure and preserve flag-store health in one read."""

    def __init__(self, feature_flags: FeatureFlagService) -> None:
        self._feature_flags = feature_flags

    def resolve(self, user: User) -> CrtExposure:
        overlay = self._feature_flags.repository.read()
        if overlay.degraded:
            raise CrtFeatureFlagUnavailableError()

        entry = overlay.flags.get("crt_canvas")
        if entry is None or entry.mode is FlagMode.OFF:
            return CrtExposure(effective=False)
        if entry.mode is FlagMode.ON:
            return CrtExposure(effective=True)
        return CrtExposure(effective=user.id in entry.selected_users)


__all__ = [
    "CrtExposure",
    "CrtExposureService",
    "CrtFeatureFlagUnavailableError",
]
