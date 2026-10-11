import pytest

from app.infrastructure.ai.components import COMPONENTS
from evals import report, variants
from evals.runner import Backends, build_input, run_cases
from evals.schema import EvalCase
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

LESSON = {"source_text": "shoe", "locale": "en-US", "introduction": "读 shoe。", "reading_guide": "sh 发 /ʃ/。", "notes": []}
GOOD = tutor_raw("pronounce", "读 shoe。", relation=None, lesson=LESSON)
# Still rejected: giving the answer to the Ward's own work product.
BAD = tutor_raw("answer", "答案是 5")


def _case(case_id="turn-test-00", status="proposed", tags=("pronounce",), **fields) -> EvalCase:
    base = {
        "id": case_id, "component": "tutoring.turn", "conversation_id": "abc12345", "turn_index": 0,
        "student_said": "这个单词怎么读？", "source": "real", "label_status": status, "tags": list(tags),
        "expect": {"outcome_in": ["pronounce"]},
    }
    if status == "confirmed":
        base["reviewed_by"] = "johan"
    return EvalCase.model_validate({**base, **fields})


def _run(cases, *raws, samples=3, **kwargs):
    backends = {"tutoring.turn": Backends(tutor_model=StaticTutorModel(*raws), leak_judge=StaticLeakJudge(False))}
    return run_cases(cases, backends, samples=samples, workers=1, **kwargs)


def test_wilson_interval_matches_known_values():
    assert report.wilson(0, 0) == (0.0, 1.0)
    low, high = report.wilson(5, 10)
    assert (round(low, 3), round(high, 3)) == (0.237, 0.763)
    low, high = report.wilson(10, 10)
    assert high == 1.0 and round(low, 3) == 0.722


def test_samples_are_repeated_and_aggregated_per_case():
    results = _run([_case()], GOOD, samples=4)
    assert len(results[0].samples) == 4 and all(s.passed for s in results[0].samples)
    summary = report.summarize(results)
    group = summary["primary"]["proposed"]["overall"]
    assert group["cases_stable_pass"]["k"] == 1 and group["samples"]["k"] == 4


def test_flaky_and_always_failing_cases_are_told_apart():
    flaky = _run([_case("turn-flaky-00")], GOOD, BAD, GOOD, samples=3)  # last raw repeats; idx0=GOOD idx1=BAD idx2=GOOD
    failing = _run([_case("turn-bad-00")], BAD, samples=3)
    group = report.summarize(flaky + failing)["primary"]["proposed"]["overall"]
    assert (group["cases_flaky"], group["cases_always_fail"], group["cases_stable_pass"]["k"]) == (1, 1, 0)


def test_guardrail_counts_fallbacks_and_names_the_reason():
    summary = report.summarize(_run([_case()], BAD, samples=3))
    assert summary["guardrail"]["fallback_rate"]["k"] == 3
    assert summary["guardrail"]["fallback_reasons"] == {"reveals_protected_work_product": 3}


def test_confirmed_and_proposed_are_reported_apart_and_needs_decision_is_not_scored():
    results = _run([
        _case("turn-a-00", "confirmed"), _case("turn-b-00", "proposed"), _case("turn-c-00", "needs_decision"),
    ], GOOD, samples=2)
    summary = report.summarize(results)
    assert summary["primary"]["confirmed"]["overall"]["cases"] == 1
    assert summary["primary"]["proposed"]["overall"]["cases"] == 1
    assert "turn-c-00" in summary["outcomes"]


def test_small_dataset_is_labelled_a_smoke_test_not_evidence():
    summary = report.summarize(_run([_case("turn-a-00", "confirmed")], GOOD, samples=2))
    assert any("只能当冒烟" in note for note in summary["notes"])
    assert any("没有 confirmed" in n for n in report.summarize(_run([_case()], GOOD))["notes"])


def test_missing_image_is_skipped_not_passed_or_failed(tmp_path):
    case = _case(images=["img-aaaaaaaaaaaa.jpg"])
    results = _run([case], GOOD, assets_dir=tmp_path)
    assert results[0].status == "skipped" and results[0].skip_reason.startswith("missing_asset")
    assert results[0].samples == []
    summary = report.summarize(results)
    assert summary["primary"]["proposed"]["overall"]["cases"] == 0
    assert summary["skipped"] == {"turn-test-00": results[0].skip_reason}


def test_images_reach_the_model_as_numbered_data_urls(tmp_path):
    (tmp_path / "img-aaaaaaaaaaaa.jpg").write_bytes(b"\xff\xd8jpeg")
    (tmp_path / "img-bbbbbbbbbbbb.png").write_bytes(b"\x89PNGdata")
    case = _case(history=[{"author": "ward", "text": "看图", "images": ["img-aaaaaaaaaaaa.jpg"]}],
                 images=["img-bbbbbbbbbbbb.png"])
    window, images = build_input(case, tmp_path)
    assert window[0]["image_urls"][0].startswith("data:image/jpeg;base64,")
    assert images[0].startswith("data:image/png;base64,")
    model = StaticTutorModel(GOOD)
    run_cases([case], {"tutoring.turn": Backends(tutor_model=model, leak_judge=StaticLeakJudge(False))},
              samples=1, workers=1, assets_dir=tmp_path)
    assert model.calls[0]["recent_utterances"][0]["image_urls"] and len(model.calls[0]["current_images"]) == 1


def test_instruction_is_the_production_one():
    from app.application.workflows.tutor_turn import build_tutor_instruction
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy

    model = StaticTutorModel(GOOD)
    case = _case(history=[{"author": "companion", "text": "shoe"}], context={"tutoring_intent": "pronunciation"})
    run_cases([case], {"tutoring.turn": Backends(tutor_model=model, leak_judge=StaticLeakJudge(False))},
              samples=1, workers=1)
    expected = build_tutor_instruction(
        content="这个单词怎么读？", permit=TutorPermitPolicy.permit(None),
        history_candidates=[{"ref": "u0", "author": "companion", "text": "shoe"}], tutoring_intent="pronunciation",
    )
    assert model.calls[0]["instruction"] == expected


def test_results_serialise_without_losing_failure_reasons():
    rows = report.to_json(_run([_case()], BAD, samples=1))
    assert rows[0]["samples"][0]["reason"] == "reveals_protected_work_product"
    assert rows[0]["samples"][0]["passed"] is False


def test_text_report_names_failing_cases():
    results = _run([_case()], BAD, samples=2)
    meta = {"component": "tutoring.turn", "component_version": "v1", "model": "m", "variant": "baseline",
            "samples": 2, "dataset_hash": "h", "git_sha": "g"}
    text = report.render_text(meta, report.summarize(results), results)
    assert "turn-test-00" in text and "reveals_protected_work_product" in text


# ---- variants: evaluation-process only ---------------------------------------------------------

def test_baseline_variant_is_the_registered_component():
    assert variants.resolve_spec("tutoring.turn") == COMPONENTS.get("tutoring.turn")


def test_model_override_changes_only_the_model():
    spec = variants.resolve_spec("tutoring.turn", model="qwen3-vl-flash")
    registered = COMPONENTS.get("tutoring.turn")
    assert spec.model == "qwen3-vl-flash" and spec.prompt is registered.prompt and spec.version == registered.version


def test_prompt_variant_removes_exactly_one_clause_and_leaves_the_registry_alone():
    registered = COMPONENTS.get("tutoring.turn")
    before = registered.prompt.digest
    spec = variants.resolve_spec("tutoring.turn", variant="drop-no-guess-clause")
    assert "不要自己补一个对象，" in registered.prompt.text and "不要自己补一个对象，" not in spec.prompt.text
    assert len(registered.prompt.text) - len(spec.prompt.text) == len("不要自己补一个对象，")
    assert spec.prompt.id.endswith("+drop-no-guess-clause") and spec.prompt.digest != before
    assert COMPONENTS.get("tutoring.turn").prompt.digest == before


def test_unknown_variant_and_stale_variant_fail_loudly(monkeypatch):
    with pytest.raises(ValueError, match="unknown variant"):
        variants.resolve_spec("tutoring.turn", variant="nope")
    monkeypatch.setattr(variants, "_NO_GUESS", "这句话已经不在 prompt 里")
    monkeypatch.setitem(variants.VARIANTS, "drop-no-guess-clause",
                        lambda spec: variants._edit_prompt(spec, "drop-no-guess-clause", variants._NO_GUESS, ""))
    with pytest.raises(ValueError, match="no longer applies"):
        variants.resolve_spec("tutoring.turn", variant="drop-no-guess-clause")


def test_cli_variant_choices_match_the_registered_variants():
    from evals.__main__ import VARIANT_NAMES

    assert set(VARIANT_NAMES) == set(variants.VARIANTS)
