"""Contract for looking up a player's STRATZ profile by Steam32 account ID."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

SteamAccountId = Annotated[StrictInt, Field(ge=1, le=2**32 - 1)]


class PlayerProfileInput(BaseModel):
    """Look up one exact Steam32 account; this does not accept names or Steam64 IDs."""

    model_config = ConfigDict(extra="forbid")

    steam_account_id: SteamAccountId = Field(
        description="Exact unsigned 32-bit Steam account ID, not a Steam64 ID or player name."
    )


class PlayerProfileResult(BaseModel):
    """Source profile observation; `found=False` is not proof the account does not exist."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    steam_account_id: SteamAccountId
    provider: Literal["stratz"]
    retrieved_at: datetime = Field(description="Time this response was retrieved, with timezone.")
    found: StrictBool = Field(
        description=(
            "Whether this response contained a usable profile object. False does not prove "
            "the Steam account is absent or has no Dota 2 history."
        )
    )
    profile: dict[str, JsonValue] | None = Field(
        description=(
            "Source profile object preserved as JSON, or null when no usable object was returned."
        )
    )

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_profile_presence(self) -> PlayerProfileResult:
        if self.found and not self.profile:
            raise ValueError("found profiles must be non-empty JSON objects")
        if not self.found and self.profile is not None:
            raise ValueError("profile must be null when found is false")
        return self
