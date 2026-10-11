"""Named candidates, valid only inside an evaluation process.

A variant never touches the component registry or ``AI_MODEL_OVERRIDES``. To adopt one,
make it an explicit, versioned component change with its own regression (design doc §七).
Change one thing per variant so a difference can be attributed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from app.infrastructure.ai.components import COMPONENTS, ComponentSpec
from app.infrastructure.ai.prompts import PromptTemplate

# The sentence in WINDOW_RULE that tells the model not to fill in an object itself.
_NO_GUESS = "不要自己补一个对象，"


def _edit_prompt(spec: ComponentSpec, label: str, old: str, new: str) -> ComponentSpec:
    prompt = spec.prompt
    if not isinstance(prompt, PromptTemplate) or old not in prompt.text:
        raise ValueError(f"variant {label} no longer applies to {spec.component_id}: prompt text changed")
    return replace(spec, prompt=PromptTemplate(f"{prompt.id}+{label}", prompt.text.replace(old, new)))


VARIANTS: dict[str, Callable[[ComponentSpec], ComponentSpec]] = {
    "baseline": lambda spec: spec,
    # Experiment from the pronunciation incident: does the "never guess the referent" clause
    # push the model to clarify when the referent is the sentence it just spoke?
    "drop-no-guess-clause": lambda spec: _edit_prompt(spec, "drop-no-guess-clause", _NO_GUESS, ""),
}


def resolve_spec(component_id: str, *, model: str | None = None, variant: str = "baseline") -> ComponentSpec:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; known: {sorted(VARIANTS)}")
    spec = VARIANTS[variant](COMPONENTS.get(component_id))
    return replace(spec, model=model) if model else spec
