"""Standalone Langfuse Code Evaluator; runtime supplies Score/EvaluationResult.

No app imports or external packages. Runner supplies checkpoint evidence in
metadata.duxue_eval; missing capture must never be treated as an empty trace.
"""
import math

VERSION = 'duxue-deterministic.v1'

OUTCOMES = {
    "answer",
    "hint_like",
    "chat",
    "clarify",
    "redirect",
    "pronounce",
    "blocked",
    "fallback",
}

INTENTS = {"planning", "tutoring", "reflection", "unclear"}

FIELDS = {
    "outcome": ("str", OUTCOMES),
    "intent": ("str", INTENTS),
    "answer_protected": ("bool", None),
    "selected_images": ("list", None),
    "visual_present": ("bool", None),
    "visual_kind": (
        "nullable_str",
        {"steps", "compare", "segment", "number_line", "svg"},
    ),
    "review_conclusion": (
        "nullable_str",
        {"all_correct", "some_incorrect", "uncertain", "not_checking"},
    ),
    "lesson_sources": ("list", None),
    "lesson_count": ("int", None),
    "leaks": ("bool", None),
    "reason": ("nullable_str", None),
    "exit_gate.leaks": ("bool", None),
    "exit_gate.reason": ("nullable_str", None),
    "exit_gate.answer_protected": ("bool", None),
    "image_target_unambiguous": ("bool", None),
    "history_isolated": ("bool", None),
    "latency_ms": ("number", None),
}


def exact(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    return a == b


def valid(field, value):
    kind, choices = FIELDS[field]
    if kind == 'nullable_str' and value is None:
        return True
    allowed = {
        'str': lambda: type(value) is str,
        'nullable_str': lambda: type(value) is str,
        'bool': lambda: type(value) is bool,
        'int': lambda: type(value) is int and value >= 0,
        'number': lambda: type(value) in (int, float) and math.isfinite(value) and value >= 0,
        'list': lambda: type(value) is list and all(type(x) is str and x for x in value),
    }
    return allowed[kind]() and (choices is None or value in choices)


def check(rule, observed, capture):
    if 'field' in rule:
        if set(rule) != {'id', 'field', 'op', 'expected'}:
            raise ValueError('invalid field assertion shape')
        field, op, expected = rule['field'], rule['op'], rule['expected']
        if field not in FIELDS or op not in {'eq', 'in', 'not_in', 'set_eq', 'lte', 'gte'}:
            raise ValueError('unknown field/operator')
        kind = FIELDS[field][0]
        if op in ('in', 'not_in'):
            if kind == 'list' or type(expected) is not list or not expected or not all(valid(field, x) for x in expected):
                raise ValueError('invalid membership expectation')
        elif not valid(field, expected):
            raise ValueError('invalid expected type/value')
        if op == 'set_eq' and kind != 'list':
            raise ValueError('set_eq requires list')
        if op in ('lte', 'gte') and kind not in ('int', 'number'):
            raise ValueError('comparison requires number')
        if field not in observed or not valid(field, observed[field]):
            raise ValueError('missing/invalid captured field: ' + field)
        actual = observed[field]
        passed = {'eq': lambda: exact(actual, expected),
                  'in': lambda: any(exact(actual, x) for x in expected),
                  'not_in': lambda: all(not exact(actual, x) for x in expected),
                  'set_eq': lambda: set(actual) == set(expected),
                  'lte': lambda: actual <= expected,
                  'gte': lambda: actual >= expected}[op]()
    else:
        action = rule.get('assert')
        keys = {'tool_called': {'with_name'}, 'parameter_match': {'tool', 'param', 'equals'}, 'no_forbidden_tools': {'forbidden'}}
        if action not in keys or set(rule) != {'id', 'assert'} | keys[action]:
            raise ValueError('unknown/invalid tool assertion')
        for key in keys[action] - {'equals', 'forbidden'}:
            if type(rule[key]) is not str or not rule[key]:
                raise ValueError('invalid tool assertion parameter')
        if action == 'no_forbidden_tools' and (type(rule['forbidden']) is not list or not rule['forbidden'] or not all(type(x) is str and x for x in rule['forbidden'])):
            raise ValueError('invalid forbidden list')
        actual, expected = observed.get('tool_calls'), rule
        if capture.get('tool_calls') is not True or type(actual) is not list or any(type(c) is not dict or type(c.get('name')) is not str or type(c.get('args')) is not dict for c in actual):
            raise ValueError('missing/incomplete tool capture')
        if action == 'tool_called':
            passed = any(c['name'] == rule['with_name'] for c in actual)
        elif action == 'parameter_match':
            passed = any(c['name'] == rule['tool'] and rule['param'] in c['args'] and exact(c['args'][rule['param']], rule['equals']) for c in actual)
        else:
            passed = all(c['name'] not in rule['forbidden'] for c in actual)
    return {'id': rule['id'], 'status': 'pass' if passed else 'fail', 'actual': actual, 'expected': expected, 'is_tool': 'assert' in rule}


def evaluate(ctx):
    metadata = ctx.observation.metadata
    payload = metadata.get('duxue_eval') if type(metadata) is dict else None
    if type(payload) is not dict or payload.get('schema_version') != 'duxue-eval-observation.v1':
        raise ValueError('missing duxue evaluation evidence envelope')
    if payload.get('execution_status') != 'completed':
        raise ValueError('checkpoint not completed; retain runner error/not_run status')
    grading = payload.get('grading')
    rules = grading.get('deterministic') if type(grading) is dict else None
    if type(rules) is not list or not rules or len(rules) > 200:
        raise ValueError('missing/oversized deterministic specification')
    ids = [r.get('id') if type(r) is dict else None for r in rules]
    if any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('missing/duplicate assertion id')
    observed, capture = payload.get('observed'), payload.get('capture_complete', {})
    if type(observed) is not dict or type(capture) is not dict:
        raise ValueError('invalid evidence shape')
    grades = [check(r, observed, capture) for r in rules]
    proof = {'grader_version': VERSION, 'scope': 'checkpoint', 'grades': grades}
    scores = [Score(name='eval.deterministic_pass', value=all(g['status'] == 'pass' for g in grades), data_type='BOOLEAN', comment='全部声明断言通过才为true；逐项证据见metadata。', metadata=proof)]
    tool_grades = [g for g in grades if g['is_tool']]
    if tool_grades:
        scores.append(Score(name='eval.tool_correctness', value=all(g['status'] == 'pass' for g in tool_grades), data_type='BOOLEAN', comment='仅覆盖声明的工具调用/参数/禁用工具断言，不评价工具结果的语义使用。', metadata={'grader_version': VERSION, 'scope': 'checkpoint', 'grades': tool_grades}))
    return EvaluationResult(scores=scores)
