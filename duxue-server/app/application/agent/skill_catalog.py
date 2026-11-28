"""Bootstrap declarations and code-owned ceilings for the Admin skill catalog."""

from functools import lru_cache
import json
from pathlib import Path

from app.application.agent.registry import SkillRegistry


@lru_cache(maxsize=1)
def bootstrap_skills():
    directory = Path(__file__).with_name("skills")
    return {
        "skills/" + path.name: json.loads(path.read_text())
        for path in sorted(directory.glob("*.json"))
    }


def configured_skills(files):
    declarations = {
        path: spec for path, spec in files.items() if path.startswith("skills/")
    }
    if not declarations:
        return {}
    defaults = bootstrap_skills()
    if declarations.keys() != defaults.keys():
        raise ValueError("incomplete education skill catalog")
    registry = SkillRegistry()
    for path, declaration in declarations.items():
        registry.register_skill(declaration)
        baseline = defaults[path]
        for field in ("id", "kind", "output_artifact_type"):
            if declaration.get(field) != baseline.get(field):
                raise ValueError(f"{path}: protected {field} changed")
        if set(declaration["required_gates"]) != set(baseline["required_gates"]):
            raise ValueError(f"{path}: mandatory gates changed")
        if not set(declaration["tools"]).issubset(baseline["tools"]):
            raise ValueError(f"{path}: tool authority cannot expand")
    return declarations
