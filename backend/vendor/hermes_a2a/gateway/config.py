"""The two ``gateway.config`` names the vendored A2A adapter imports.

BrainBuddy-owned stub (spec 014 FR-017, research.md Decision G). ``adapter.py``
uses only ``Platform("a2a")`` and reads ``config.extra`` / ``config.enabled``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class Platform(Enum):
    """Platform identity, with the upstream ``_missing_`` pseudo-member rule.

    The adapter constructs ``Platform("a2a")`` and the base class reads
    ``platform.value``. Upstream creates a cached pseudo-member for a plugin
    platform name so that ``Platform("a2a") is Platform("a2a")`` holds; that
    identity stability matters because the adapter compares platforms, so the
    stub reproduces it rather than returning a fresh object each call.
    """

    LOCAL = "local"

    @classmethod
    def _missing_(cls, value: object) -> "Platform | None":
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().lower()
        cached = cls._value2member_map_.get(normalized)
        if cached is not None:
            return cached  # type: ignore[return-value]
        pseudo = object.__new__(cls)
        pseudo._value_ = normalized
        pseudo._name_ = normalized.upper().replace("-", "_").replace(" ", "_")
        cls._value2member_map_[normalized] = pseudo
        cls._member_map_[pseudo._name_] = pseudo
        return pseudo


@dataclass
class PlatformConfig:
    """One platform's configuration block.

    ``extra`` is the free-form section the A2A adapter reads its port and
    served-agent routing out of.
    """

    enabled: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


__all__ = ["Platform", "PlatformConfig"]
