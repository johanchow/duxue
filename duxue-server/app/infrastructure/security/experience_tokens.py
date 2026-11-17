"""Short-lived, purpose-bound Guardian experience state; never an access token."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.bootstrap.settings import settings


def seal(guardian_id: str, purpose: str, data: dict) -> str:
    payload = json.dumps({"owner": guardian_id, "purpose": purpose,
                          "exp": int(time.time()) + 4 * 3600, "data": data},
                         ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    signature = hmac.new(settings.secret_key.encode(), b"guardian-experience.v1:" + encoded.encode(),
                         hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def unseal(token: str, guardian_id: str, purpose: str) -> dict:
    try:
        if len(token) > 64000:
            raise ValueError("oversized state")
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(settings.secret_key.encode(), b"guardian-experience.v1:" + encoded.encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        value = json.loads(base64.b64decode(encoded, altchars=b"-_", validate=True))
        if (value["owner"] != guardian_id or value["purpose"] != purpose
                or value["exp"] <= time.time() or not isinstance(value["data"], dict)):
            raise ValueError("invalid scope")
        return value["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("invalid or expired experience state") from error
