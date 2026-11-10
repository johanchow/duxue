"""Internal control API. Never grants direct access to children or business writes."""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import snapshot_bundle
from app.agent_specs.debug_contracts import (
    DebugInput,
    debug_capabilities,
    resolve_target,
)


def internal_admin(authorization: str | None = Header(default=None)):
    secret = os.getenv("AGENT_ADMIN_INTERNAL_TOKEN", "")
    if not secret or not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "internal admin authentication required")
    if os.getenv("APP_ENV", "test") in {"production", "prod"} and os.getenv("AGENT_ADMIN_CONTROL_PROCESS") != "1":
        raise HTTPException(403, "production configuration control is disabled on this service")


router = APIRouter(
    prefix="/internal/agent-admin", dependencies=[Depends(internal_admin)]
)


class BundleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle: dict


class DebugRequest(BundleInput):
    input: DebugInput


def _catalog(bundle):
    from app.agent_specs import release_runtime
    from app.agent_specs.definitions import use_definitions
    from app.agent_specs.inventory import management_inventory
    compiled = compile_bundle(bundle)
    with use_definitions(compiled.catalog):
        data = {"bundle": bundle, **management_inventory(bundle)}
    current = release_runtime.runtime.current if release_runtime.runtime else None
    data["debug_capabilities"] = debug_capabilities()
    data["runtime"] = {
        "release_id": current[0]["id"] if current else None,
        "digest": current[1].digest if current else None,
        "source": "admin" if release_runtime.runtime else "snapshot",
    }
    return data


@router.post("/catalog")
def catalog_from_bundle(body: BundleInput):
    try:
        return _catalog(body.bundle)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, str(error)[:1500]) from error


@router.get("/catalog")
def catalog():
    try:
        return _catalog(snapshot_bundle())
    except ValueError as error:
        raise HTTPException(503, str(error)) from error


@router.post("/validate")
def validate(body: BundleInput):
    try:
        snapshot = compile_bundle(body.bundle)
        from app.application.workflows.image_review import require_configuration
        try:
            require_configuration(body.bundle)
            runtime_errors = []
        except ValueError as error:
            runtime_errors = [str(error)]
        return {
            "valid": True,
            "runtime_ready": not runtime_errors,
            "runtime_errors": runtime_errors,
            "digest": snapshot.digest,
            "compatibility": body.bundle["compatibility"],
        }
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, str(error)[:1500]) from error


@router.post("/debug")
def debug(body: DebugRequest):
    try:
        snapshot = compile_bundle(body.bundle)
        resolve_target(body.input, snapshot.catalog)
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    env = {
        **os.environ,
        "OTEL_SDK_DISABLED": "true",
        "LANGFUSE_ENABLED": "false",
        "AGENT_DEBUG_AUDIT_ENABLED": "false",
    }
    try:
        process = subprocess.run(
            [sys.executable, "-m", "app.agent_specs.debug_worker"],
            input=body.model_dump_json(),
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
            cwd=Path(__file__).resolve().parents[3],
            env=env,
        )
        result = json.loads(process.stdout)
        if process.returncode:
            raise HTTPException(502, result.get("message", "isolated debug failed"))
        return result
    except subprocess.TimeoutExpired as error:
        raise HTTPException(504, "isolated debug exceeded 240 seconds") from error
    except json.JSONDecodeError as error:
        raise HTTPException(502, "invalid isolated worker response") from error
