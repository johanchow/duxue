"""Prompt adapters; the bodies live beside their Agent or Judge definition."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

import hashlib
import json
import re
from dataclasses import dataclass

from app.agent_specs.definitions import load_definitions


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


@dataclass(frozen=True)
class DynamicPrompt:
    id: str
    template: str
    variables: dict[str, dict]

    def render(self, context: dict) -> str:
        if set(context) != set(self.variables):
            raise ValueError(f"{self.id}: prompt context fields differ from declaration")
        values = {}
        for name, declaration in self.variables.items():
            value = context[name]
            expected = declaration["type"]
            if ((expected == "string" and not isinstance(value, str))
                    or (expected == "array" and not isinstance(value, list))
                    or (expected == "object" and not isinstance(value, dict))):
                raise ValueError(f"{self.id}: invalid {name} type")
            rendered = value if expected == "string" else json.dumps(value, ensure_ascii=False)
            values[name] = rendered
        return re.sub(r"\{\{([a-z_][a-z_0-9]*)\}\}", lambda match: values[match.group(1)], self.template)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.template.encode()).hexdigest()


@lru_cache(maxsize=16)
def _load_prompts(definitions) -> dict[str, PromptTemplate | DynamicPrompt]:
    result: dict[str, PromptTemplate | DynamicPrompt] = {}
    for unit in definitions.units.values():
        for definition in (unit.prompt, *unit.prompt.fragments.values()):
            prompt = (
                PromptTemplate(definition.id, definition.template)
                if getattr(definition, "delivery", None) == "system" else
                DynamicPrompt(definition.id, definition.template, definition.variables)
            )
            if prompt.id in result:
                raise ValueError(f"duplicate Prompt ID {prompt.id}")
            result[prompt.id] = prompt
    return result


class PromptRegistry(Mapping):
    def __getitem__(self, key):
        return _load_prompts(load_definitions())[key]

    def __iter__(self):
        return iter(_load_prompts(load_definitions()))

    def __len__(self):
        return len(_load_prompts(load_definitions()))


PROMPTS = PromptRegistry()


def render_fragment(unit_id: str, name: str, **context) -> str:
    """Code selects a named instruction; inserted data is never templated again."""
    fragment = load_definitions().units[unit_id].prompt.fragments[name]
    return DynamicPrompt(fragment.id, fragment.template, fragment.variables).render(context)
