"""Prompt adapters; the bodies live beside their Agent or Judge definition."""

from __future__ import annotations

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


def _load_prompts() -> dict[str, PromptTemplate | DynamicPrompt]:
    result: dict[str, PromptTemplate | DynamicPrompt] = {}
    for unit in load_definitions().units.values():
        definition = unit.prompt
        prompt = (
            PromptTemplate(definition.id, definition.template)
            if definition.delivery == "system" else
            DynamicPrompt(definition.id, definition.template, definition.variables)
        )
        if prompt.id in result:
            raise ValueError(f"duplicate Prompt ID {prompt.id}")
        result[prompt.id] = prompt
    return result


PROMPTS = _load_prompts()
