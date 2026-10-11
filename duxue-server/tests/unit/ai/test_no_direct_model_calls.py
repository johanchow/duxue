"""Every LLM/VLM call goes through the component registry.

``inference.py`` (VLM frame analysis: batch + realtime, a different call shape)
is the one known pending migration; remove it from the allow-list when moved.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "app"
EVALS = ROOT / "evals"
ALLOWED = {
    "infrastructure/ai/components.py",
    "infrastructure/ai/client.py",  # the shared client factory itself
    "infrastructure/ai/inference.py",  # pending: VLM component
}


def test_no_module_calls_the_provider_sdk_directly():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in ALLOWED:
            continue
        text = path.read_text()
        if "chat.completions" in text or "dashscope_client(" in text:
            offenders.append(rel)
    assert not offenders, f"call models through components.invoke_json_component: {offenders}"


def test_offline_evaluation_also_goes_through_the_registry():
    """evals/ may pick a spec or a model name, but never talks to the provider itself."""
    offenders = [
        path.relative_to(ROOT).as_posix() for path in EVALS.rglob("*.py")
        if "chat.completions" in path.read_text() or "dashscope_client(" in path.read_text()
    ]
    assert not offenders, f"evals must call components.invoke_json_component: {offenders}"
