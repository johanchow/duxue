from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActivityCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str
    activity: Literal[
        "writing",
        "reading_material",
        "handling_material",
        "still_with_material",
        "other_visible_activity",
        "away",
        "unknown",
    ]
    evidence_frame_ids: list[str] = Field(min_length=1, max_length=8)
    uncertainty_reason: str | None = None


class VisibleActivityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cells: list[ActivityCell] = Field(max_length=4)


class SupportOpportunityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["offer_help", "invite_return", "none", "uncertain"]
    evidence_refs: list[str] = Field(max_length=16)
    observed_basis: str = Field(max_length=1000)
    uncertainty_reason: str | None = None
