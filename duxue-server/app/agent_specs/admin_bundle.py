"""Complete Admin artifacts with code-owned contracts and editable component values."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.agent_specs.definitions import DefinitionCatalog
from app.agent_specs.configuration import code_contract

# Every JSON is carried by the published artifact. Code owns the file whitelist
# and protected contract; values are not filled from local defaults at load time.
EDITABLE_FILES = tuple(sorted(code_contract()["files"]))

def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _artifact_document(raw):
    doc = copy.deepcopy(raw)
    if doc.get("kind") in {"agent", "gate", "tool", "workflow"}:
        doc.pop("version", None)
    for model in doc.get("models", []):
        model.pop("version", None)
    if "prompt" in doc:
        doc["prompt"]["id"] = doc["id"] + ".prompt"
        for name, fragment in doc["prompt"].get("fragments", {}).items():
            fragment["id"] = doc["id"] + ".fragment." + name
    return doc


def _frozen(doc):
    result = copy.deepcopy(doc)
    if doc.get("kind") in {"agent", "gate", "tool"}:
        result.pop("display_name", None)
        result.pop("description", None)
    if result.get("implementation") in {"llm", "judge"}:
        for model in result["models"]:
            for key in ("name", "temperature", "max_output_tokens", "timeout_ms"):
                model.pop(key, None)
        result["prompt"].pop("template")
        for fragment in result["prompt"].get("fragments", {}).values():
            fragment.pop("template")
        result.pop("tools")
    elif result.get("handler_id") == "tool.static_result":
        result.pop("static_result")
    return result


def contract_compatibility() -> str:
    from app.agent_specs.registrations import WORKFLOW_BINDINGS
    return digest({
        "files": code_contract()["files"],
        "handlers": {key: {field: sorted(items) for field, items in value.items()}
                     for key, value in WORKFLOW_BINDINGS.items()},
        "protocol": 3,
    })


@dataclass(frozen=True)
class CompiledBundle:
    digest: str
    catalog: DefinitionCatalog
    bundle: dict


def compile_bundle(bundle: dict) -> CompiledBundle:
    baseline = {"format_version": 3, "compatibility": contract_compatibility(), "files": code_contract()["files"]}
    if (
        set(bundle) != set(baseline)
        or type(bundle["format_version"]) is not int
        or bundle["format_version"] != 3
    ):
        raise ValueError("invalid bundle format")
    if bundle["compatibility"] != baseline["compatibility"]:
        raise ValueError(
            "code compatibility mismatch; export a new draft from the current server"
        )
    if not isinstance(bundle["files"], dict) or set(bundle["files"]) != set(
        EDITABLE_FILES
    ):
        raise ValueError(
            "bundle files differ from the registered complete configuration manifest"
        )
    for name, doc in bundle["files"].items():
        original = baseline["files"][name]
        if "version" in doc or any(
            "version" in model for model in doc.get("models", [])
        ):
            raise ValueError("manual configuration versions are not supported")
        try:
            fixed = _frozen(doc)
        except (AttributeError, KeyError, TypeError) as error:
            raise ValueError(f"{name}: malformed configuration") from error
        if fixed != original:
            raise ValueError(f"{name}: read-only contract or workflow changed")
        if "models" in doc and not set(doc["tools"]).issubset(code_contract()["tool_authority"][doc["id"]]):
            raise ValueError(f"{name}: tool authority cannot expand")
    bundle_id = digest(bundle)
    with tempfile.TemporaryDirectory(prefix="duxue-config-") as directory:
        root = Path(directory)
        for name, raw in bundle["files"].items():
            doc = copy.deepcopy(raw)
            if doc.get("kind") in {"agent", "gate", "tool", "workflow"}:
                doc["version"] = bundle_id
            if "prompt" in doc:
                doc["prompt"]["id"] += "+" + bundle_id[:12]
                for fragment in doc["prompt"].get("fragments", {}).values():
                    fragment["id"] += "+" + bundle_id[:12]
                for model in doc["models"]:
                    model["version"] = bundle_id
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False))
        catalog = DefinitionCatalog(root)
        catalog.artifact_digest = bundle_id
    main = catalog.units["tutoring.turn"].models[0].name
    if any(
        catalog.units[name].models[0].name == main
        for name in ("tutoring.leak-judge", "tutoring.visual-leak-judge")
    ):
        raise ValueError("independent Judges must not share the primary tutor model")
    return CompiledBundle(bundle_id, catalog, copy.deepcopy(bundle))
