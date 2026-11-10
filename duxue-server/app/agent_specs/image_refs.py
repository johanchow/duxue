"""Content identities for authorized images; no storage paths or network reads."""
from __future__ import annotations

import base64
import hashlib


def image_ref(value: str) -> str:
    payload = value.encode()
    if value.startswith('data:') and ';base64,' in value:
        payload = base64.b64decode(value.split(';base64,', 1)[1], validate=True)
    return 'img_' + hashlib.sha256(payload).hexdigest()[:24]


def image_manifest(images: list[str | None]) -> list[dict]:
    return [{'image_id': index + 1, 'image_ref': image_ref(value)}
            for index, value in enumerate(images) if value]
