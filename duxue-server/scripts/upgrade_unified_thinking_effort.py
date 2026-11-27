"""Migrate an Admin snapshot to abstract effort tiers and an explicit-only leak judge."""
from copy import deepcopy

MARKER = "[explicit-violation-only.v1]"
RULE = """[explicit-violation-only.v1]
仅在有明确依据确认候选违反对应规则时，将new_final_answer、complete_solution、choice_verdict或premature_conclusion设为true。不确定、题面模糊、缺少dossier或核验工具记录本身不等于泄露或违规，不得据此推断违规。student_answer_correct无法确定时填null，不能当成false；仅明确核验错误才填false。按回复实际确认的题项核验，不因其他题未核验而否定已确认部分。明确补出受保护答案、完整解法、试探选择项，或明确错误确认仍须如实标记。"""


def upgrade(record):
    from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
    from app.infrastructure.ai.thinking_policy import resolve_provider_thinking
    from scripts.upgrade_companion_intent_hints import upgrade as upgrade_intent

    result = upgrade_intent(record)
    bundle = deepcopy(result['bundle'])
    for doc in bundle['files'].values():
        for model in doc.get('models', []):
            effort = model.get('thinking_effort') or resolve_provider_thinking(
                model['name'], enable_thinking=model.get('enable_thinking', False),
                thinking_budget=model.get('thinking_budget'),
                reasoning_effort=model.get('guardian_t1_reasoning_effort'),
            ).effective_effort
            for key in ('enable_thinking', 'thinking_budget', 'guardian_t1_reasoning_effort'):
                model.pop(key, None)
            if doc['id'] == 'tutoring.turn' and effort == 'high':
                effort = 'medium'  # Deep reasoning belongs to the blueprint solver.
            model['thinking_effort'] = 'off' if doc['id'] in {
                'tutoring.leak-judge', 'tutoring.visual-leak-judge',
            } else effort
    judge = bundle['files']['gates/tutoring.leak-judge.json']['prompt']
    if MARKER not in judge['template']:
        judge['template'] += '\n\n' + RULE
    bundle['compatibility'] = contract_compatibility(bundle['files'])
    result.update(bundle=bundle, digest=compile_bundle(bundle).digest)
    return result


if __name__ == '__main__':
    import argparse
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False, indent=2))
