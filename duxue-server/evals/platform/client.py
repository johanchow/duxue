"""Explicit project-scoped connection. No production tracing initialization."""

import os
import json
from pathlib import Path

EVALUATION_ENVIRONMENT = "offline-evaluation"
RULE_ENVIRONMENTS = [
    EVALUATION_ENVIRONMENT,
    "sdk-experiment",
]  # Historical runs remain evaluable.

RESOURCES = Path(__file__).resolve().parents[1] / "langfuse/resources.json"


def connect():
    from dotenv import load_dotenv
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    # Dedicated provider and experiment environment; no production telemetry is started.
    os.environ["OTEL_SDK_DISABLED"] = "false"
    resources = json.loads(RESOURCES.read_text())
    client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=resources["baseUrl"],
        environment=EVALUATION_ENVIRONMENT,
        tracer_provider=TracerProvider(),
        flush_at=1,
        timeout=15,
    )
    projects = client.api.projects.get()
    if resources["projectId"] not in [p.id for p in projects.data]:
        raise ValueError("Langfuse project does not match credentials")
    return client, resources


def dataset_items(client, name, version=None):
    result = []
    page = 1
    while True:
        response = client.api.dataset_items.list(
            dataset_name=name, version=version, page=page, limit=100
        )
        result.extend(response.data)
        if page >= response.meta.total_pages:
            break
        page += 1
    return result


def dump(model):
    return model.model_dump(mode="json", by_alias=True)
