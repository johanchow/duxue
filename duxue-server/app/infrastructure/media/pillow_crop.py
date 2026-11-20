"""In-memory Pillow crop adapter with strict bounds, EXIF orientation, and readability upscaling."""

from __future__ import annotations

import base64
import hashlib
import io

from PIL import Image, ImageOps

from app.application.ports.image_inspection import (
    CropBox,
    ImageInspectionPort,
    InspectImageRequest,
    InspectImageResult,
)

MAX_DECODED_BYTES = 15 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000
MIN_READABLE_SIDE = 256
MAX_OUTPUT_SIDE = 1280
MIN_SAFETY_PADDING = 0.04
RELATIVE_SAFETY_PADDING = 0.15


def _pad_bbox(b: CropBox) -> CropBox:
    """Expand model-predicted crop boxes gently so ruler origins and dimension labels aren't clipped."""
    pad_x = max(MIN_SAFETY_PADDING, RELATIVE_SAFETY_PADDING * (b.x1 - b.x0))
    pad_y = max(MIN_SAFETY_PADDING, RELATIVE_SAFETY_PADDING * (b.y1 - b.y0))
    return CropBox(
        x0=max(0.0, b.x0 - pad_x),
        y0=max(0.0, b.y0 - pad_y),
        x1=min(1.0, b.x1 + pad_x),
        y1=min(1.0, b.y1 + pad_y),
    )


class PillowImageInspector(ImageInspectionPort):
    def inspect(
        self, request: InspectImageRequest, *, authorized_images: dict[str, str]
    ) -> InspectImageResult:
        if not authorized_images:
            return InspectImageResult(status="no_match")
        data_url = authorized_images.get(request.image_ref)
        if data_url is None:
            return InspectImageResult(status="unauthorized")
        if not data_url.startswith("data:") or ";base64," not in data_url:
            return InspectImageResult(status="tool_error")

        try:
            raw_bytes = base64.b64decode(data_url.split(";base64,", 1)[1], validate=True)
            if len(raw_bytes) > MAX_DECODED_BYTES:
                return InspectImageResult(status="tool_error")
            with Image.open(io.BytesIO(raw_bytes)) as src:
                if src.width * src.height > MAX_SOURCE_PIXELS:
                    return InspectImageResult(status="tool_error")
                oriented = ImageOps.exif_transpose(src).convert("RGB")
        except Exception:  # noqa: BLE001 - corrupt image must return typed tool_error
            return InspectImageResult(status="tool_error")

        w, h = oriented.size
        padded = _pad_bbox(request.bbox)
        left = max(0, min(w - 1, int(round(padded.x0 * w))))
        top = max(0, min(h - 1, int(round(padded.y0 * h))))
        right = max(left + 1, min(w, int(round(padded.x1 * w))))
        bottom = max(top + 1, min(h, int(round(padded.y1 * h))))

        cropped = oriented.crop((left, top, right, bottom))
        cw, ch = cropped.size
        # Gently upscale tiny handwriting/subscript crops so VLMs can read fine strokes clearly
        short_side = min(cw, ch)
        long_side = max(cw, ch)
        if short_side < MIN_READABLE_SIDE and long_side * 2 <= MAX_OUTPUT_SIDE:
            scale = min(3.0, MIN_READABLE_SIDE / max(1, short_side), MAX_OUTPUT_SIDE / max(1, long_side))
            if scale > 1.05:
                cropped = cropped.resize(
                    (max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))),
                    Image.Resampling.LANCZOS,
                )
        elif long_side > MAX_OUTPUT_SIDE:
            scale = MAX_OUTPUT_SIDE / long_side
            cropped = cropped.resize(
                (max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))),
                Image.Resampling.LANCZOS,
            )

        out = io.BytesIO()
        cropped.save(out, format="PNG", optimize=True)
        out_bytes = out.getvalue()
        crop_ref = "crop_" + hashlib.sha256(out_bytes).hexdigest()[:20]
        crop_url = "data:image/png;base64," + base64.b64encode(out_bytes).decode("ascii")

        return InspectImageResult(
            status="unique",
            image_ref=request.image_ref,
            crop_ref=crop_ref,
            bbox=padded,
            width=cropped.width,
            height=cropped.height,
            label=request.label,
            crop_data_url=crop_url,
        )
