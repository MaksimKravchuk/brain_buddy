"""Bounded device-flow input; credentials never appear in response JSON."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeviceStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeviceRequest(DeviceStart):
    user_code: str = Field(
        min_length=8, max_length=9, pattern=r"^[A-HJ-NP-Z2-9]{4}-?[A-HJ-NP-Z2-9]{4}$"
    )


class DeviceDecision(DeviceRequest):
    decision: Literal["approve", "deny"]
    expected_owner: str = Field(min_length=1, max_length=160)


class DeviceToken(DeviceStart):
    device_code: str = Field(
        min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$"
    )
