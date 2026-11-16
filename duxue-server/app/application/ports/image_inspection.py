"""Read-only authorized image region cropping port for dense diagrams and handwritten drafts."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CropBox(BaseModel):
    """Normalized [0.0, 1.0] bounding box (top-left origin)."""

    model_config = ConfigDict(extra="forbid")
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def non_degenerate(self):
        if self.x1 - self.x0 < 0.02 or self.y1 - self.y0 < 0.02:
            raise ValueError("crop_box_too_small_or_inverted")
        return self


class InspectImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_ref: str = Field(min_length=5, max_length=64)
    bbox: CropBox
    label: str | None = Field(default=None, max_length=80)


class InspectImageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unique", "no_match", "unauthorized", "tool_error"]
    image_ref: str | None = None
    crop_ref: str | None = None
    bbox: CropBox | None = None
    width: int | None = None
    height: int | None = None
    label: str | None = None
    # Held only in memory for multimodal message assembly; NEVER serialized into telemetry/observations.
    crop_data_url: str | None = None

    def public_observation(self) -> dict:
        return self.model_dump(exclude={"crop_data_url"}, exclude_none=True)


class ImageInspectionPort(Protocol):
    def inspect(
        self, request: InspectImageRequest, *, authorized_images: dict[str, str]
    ) -> InspectImageResult: ...
