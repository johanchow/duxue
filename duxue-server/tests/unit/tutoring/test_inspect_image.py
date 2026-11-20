import base64
import io
import json

from PIL import Image

from app.agent_specs.contexts import tutor_turn
from app.agent_specs.image_refs import image_ref
from app.application.ports.image_inspection import CropBox, InspectImageRequest
from app.infrastructure.media.pillow_crop import PillowImageInspector


def _make_quadrant_data_url() -> str:
    """Create a 100x100 PNG: top-left red, top-right green, bottom-left blue, bottom-right white."""
    img = Image.new("RGB", (100, 100))
    for x in range(100):
        for y in range(100):
            if x < 50 and y < 50:
                color = (255, 0, 0)
            elif x >= 50 and y < 50:
                color = (0, 255, 0)
            elif x < 50 and y >= 50:
                color = (0, 0, 255)
            else:
                color = (255, 255, 255)
            img.putpixel((x, y), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def test_pillow_crop_authorized_quadrant_and_upscale():
    data_url = _make_quadrant_data_url()
    ref = image_ref(data_url)
    inspector = PillowImageInspector()

    result = inspector.inspect(
        InspectImageRequest(
            image_ref=ref,
            bbox=CropBox(x0=0.55, y0=0.05, x1=0.95, y1=0.45),
        ),
        authorized_images={ref: data_url},
    )
    assert result.status == "unique"
    assert result.crop_data_url is not None
    assert result.crop_ref is not None
    assert result.crop_ref.startswith("crop_")

    # Verify cropped pixels are purely green (top-right quadrant) and upscaled for small crop readability
    raw = base64.b64decode(result.crop_data_url.split(";base64,", 1)[1])
    cropped = Image.open(io.BytesIO(raw))
    assert cropped.width >= 80 and cropped.height >= 80
    r, g, b = cropped.getpixel((cropped.width // 2, cropped.height // 2))
    assert g > 240 and r < 15 and b < 15


def test_inspect_image_rejects_unauthorized_or_invalid_bbox():
    data_url = _make_quadrant_data_url()
    ref = image_ref(data_url)
    inspector = PillowImageInspector()

    unauth = inspector.inspect(
        InspectImageRequest(
            image_ref="img_000000000000000000000000",
            bbox=CropBox(x0=0.0, y0=0.0, x1=0.5, y1=0.5),
        ),
        authorized_images={ref: data_url},
    )
    assert unauth.status == "unauthorized"
    assert unauth.crop_data_url is None

    # Emptyauthorized map -> no_match
    empty = inspector.inspect(
        InspectImageRequest(
            image_ref=ref,
            bbox=CropBox(x0=0.0, y0=0.0, x1=0.5, y1=0.5),
        ),
        authorized_images={},
    )
    assert empty.status == "no_match"


def test_tutor_turn_context_attaches_crop_parts_without_leaking_bytes_in_json_observations():
    data_url = _make_quadrant_data_url()
    ref = image_ref(data_url)
    inspector = PillowImageInspector()
    res = inspector.inspect(
        InspectImageRequest(
            image_ref=ref,
            bbox=CropBox(x0=0.0, y0=0.0, x1=0.4, y1=0.4),
        ),
        authorized_images={ref: data_url},
    )
    public_obs = res.public_observation()
    # Public observation stored in observations/telemetry MUST NOT contain base64 image bytes
    serialized_obs = json.dumps(public_obs)
    assert "data:image" not in serialized_obs
    assert public_obs["status"] == "unique"
    assert public_obs["crop_ref"] == res.crop_ref

    parts = tutor_turn(
        envelope={"inspected_crops": [{"crop_ref": res.crop_ref, "url": res.crop_data_url}]},
        instruction='{"student_said":"看左上角"}',
        recent_utterances=[],
        current_images=[data_url],
        observations=[{"tool": "inspect_image", **public_obs}],
    )
    # Text JSON part must not contain raw crop base64 URL
    text_body = parts[0]["text"]
    assert res.crop_data_url not in text_body
    # Multimodal parts include both original image and cropped zoom image
    image_urls = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
    assert data_url in image_urls
    assert res.crop_data_url in image_urls


def test_image_prompt_exposes_not_checking_questions_contract():
    import json

    from app.agent_specs.contexts import tutor_turn

    parts = tutor_turn(envelope={}, instruction="带我理解这张题图", current_images=["data:image/png;base64,aW1hZ2U="])
    data = json.loads(parts[0]["text"])
    assert "not_checking" in data["image_review_rule"]
    assert "questions=[]" in data["image_review_rule"]


def test_pillow_crop_applies_safety_padding_to_avoid_clipping_origin():
    data_url = _make_quadrant_data_url()
    ref = image_ref(data_url)
    inspector = PillowImageInspector()

    req = InspectImageRequest(
        image_ref=ref,
        bbox=CropBox(x0=0.40, y0=0.40, x1=0.60, y1=0.60),
    )
    res = inspector.inspect(req, authorized_images={ref: data_url})
    assert res.status == "unique"
    assert res.bbox is not None
    # Expanded gently on all four sides within [0.0, 1.0]
    assert res.bbox.x0 < 0.40 and res.bbox.y0 < 0.40
    assert res.bbox.x1 > 0.60 and res.bbox.y1 > 0.60
    assert 0.0 <= res.bbox.x0 < res.bbox.x1 <= 1.0
    assert 0.0 <= res.bbox.y0 < res.bbox.y1 <= 1.0
