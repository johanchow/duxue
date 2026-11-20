"""Transport shared by the first submission and the optional cropped retry."""

import hashlib
import json
import os
import threading
import time
from urllib.parse import urlsplit

import httpx
import pymupdf

PDF_LOCK = threading.Lock()
DEFAULT_ACCOUNT = "guardian-home-qa@example.invalid"


def write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_url(value):
    address = urlsplit(value)
    if (
        address.scheme not in ("http", "https")
        or address.hostname not in ("127.0.0.1", "localhost", "::1")
        or address.username
    ):
        raise ValueError("The authenticated examination endpoint must be local")
    return value.rstrip("/")


def close_interrupted(folder):
    """Call only while holding the run's exclusive lock."""
    for path in folder.glob("*-*.json"):
        row = json.loads(path.read_text())
        if row.get("status") == "submitted":
            row.update(
                status="delivery_unknown",
                error="previous executor stopped before writing a receipt",
            )
            write(path, row)


def test_identity():
    email = os.environ.get("DUXUE_EXAM_TEST_ACCOUNT", DEFAULT_ACCOUNT)
    from app.infrastructure.persistence.database import SessionLocal
    from app.infrastructure.persistence.models import Guardian

    with SessionLocal() as db:
        g = db.query(Guardian).filter_by(email=email).one()
        return g.id, g.role


def deliver(client, identity, root, dest, subject, task, prompt, select=None):
    from app.infrastructure.security.tokens import create_access_token

    a, b, first, last = task
    if dest.exists():
        return
    auth = {
        "Authorization": "Bearer "
        + create_access_token(user_id=identity[0], role=identity[1])
    }
    with PDF_LOCK, pymupdf.open(root / subject / "paper.pdf") as doc:
        spans = (
            select(doc, subject, task)
            if select
            else [(i, doc[i].rect) for i in range(first - 1, last)]
        )
        images = [
            doc[i]
            .get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8), clip=box)
            .tobytes("jpeg", jpg_quality=90)
            for i, box in spans
        ]
    keys = []
    for data in images:
        res = client.post(
            "/guardian/experience/attachments/upload-url",
            headers=auth,
            json={"extension": "jpg", "content_type": "image/jpeg"},
        )
        res.raise_for_status()
        upload = res.json()
        client.put(
            upload["upload_url"], headers=upload["headers"], content=data
        ).raise_for_status()
        keys.append(upload["oss_key"])
    record = {
        "subject": subject,
        "questions": [a, b],
        "pages": [first, last],
        "prompt": prompt,
        "image_sha256": [hashlib.sha256(data).hexdigest() for data in images],
        "bank_hit": None,
        "status": "submitted",
    }
    if select:
        record["crops"] = [[i + 1, list(box)] for i, box in spans]
    write(dest, record)
    started = time.monotonic()
    try:
        res = client.post(
            "/guardian/experience/turn",
            headers=auth,
            json={
                "mode": "guardian_explain",
                "content": prompt,
                "attachment_keys": keys,
            },
        )
    except httpx.TransportError as exc:
        record.update(status="transport_error", error=type(exc).__name__)
    else:
        record["http"] = res.status_code
        if res.is_success:
            answer = res.json()
            record.update(
                status="answered",
                answer={
                    k: v
                    for k, v in answer.items()
                    if k in ("act", "content", "mode", "visual")
                },
            )
        else:
            record.update(status="http_error", error=res.text[:500])
    record["seconds"] = round(time.monotonic() - started, 2)
    write(dest, record)
    print(subject, a, record["status"], record.get("answer", {}).get("act"), flush=True)
