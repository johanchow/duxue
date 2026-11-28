"""Bootstrap declarations and code-owned ceilings for the unified Tool catalog."""

from functools import lru_cache
import json
from pathlib import Path

from app.application.agent.registry import ToolRegistry


@lru_cache(maxsize=1)
def bootstrap_tools() -> dict[str, dict]:
    directory = Path(__file__).with_name("tools")
    return {
        "tools/" + path.name: json.loads(path.read_text())
        for path in sorted(directory.glob("*.json"))
    }


def configured_tools(files: dict[str, dict]) -> dict[str, dict]:
    declarations = {
        path: spec for path, spec in files.items() if path.startswith("tools/")
    }
    if not declarations:
        return {}
    defaults = bootstrap_tools()
    if declarations.keys() != defaults.keys():
        raise ValueError("incomplete education tool catalog")
    registry = ToolRegistry()
    for path, declaration in declarations.items():
        registry.register_spec(declaration)
        baseline = defaults[path]
        for field in ("id", "kind", "owner_domain", "access", "handler_id"):
            if declaration.get(field) != baseline.get(field):
                raise ValueError(f"{path}: protected {field} changed")
        if declaration["timeout_ms"] > baseline["timeout_ms"]:
            raise ValueError(f"{path}: timeout_ms cannot exceed code ceiling")
    return declarations
