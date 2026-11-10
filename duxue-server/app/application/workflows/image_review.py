"""Typed, image-bound verification evidence, separate from the visible reply."""
from __future__ import annotations

import ast
import json
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

from app.agent_specs.image_refs import image_ref
from pydantic import BaseModel, ConfigDict, Field


class ImageReviewProtocolError(ValueError):
    def __init__(self, code: str, location: str | None = None):
        self.code, self.location = code, location
        super().__init__(code + (':' + location if location else ''))

    def feedback(self) -> str:
        return json.dumps({'kind': 'image_review_protocol_error', 'error_code': self.code,
                           'location': self.location}, ensure_ascii=False)


class Calculation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: str = Field(min_length=1, max_length=120)
    submitted: str = Field(min_length=1, max_length=40)

    def correct(self) -> bool:
        try:
            tree = ast.parse(self.expression, mode='eval')
        except SyntaxError as error:
            raise ValueError('invalid_calculation_syntax') from error
        if len(list(ast.walk(tree))) > 80:
            raise ValueError('calculation_too_complex')
        def number(raw):
            parsed = Decimal(raw)
            if not parsed.is_finite() or abs(parsed) > Decimal('1e12') or abs(parsed.as_tuple().exponent) > 24:
                raise ValueError('calculation_out_of_bounds')
            return Fraction(parsed)

        def value(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                result = number(ast.get_source_segment(self.expression, node))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = value(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                left, right = value(node.left), value(node.right)
                if isinstance(node.op, ast.Add): result = left + right
                elif isinstance(node.op, ast.Sub): result = left - right
                elif isinstance(node.op, ast.Mult): result = left * right
                else: result = left / right
            else:
                raise ValueError('unsupported_calculation_syntax')
            if abs(result) > 10**12 or result.denominator.bit_length() > 1024:
                raise ValueError('calculation_out_of_bounds')
            return result
        try:
            submitted = number(self.submitted)
            return value(tree.body) == submitted
        except (InvalidOperation, ArithmeticError) as error:
            raise ValueError('invalid_calculation') from error


class QuestionReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    image_ref: str = Field(pattern=r'^img_[a-f0-9]{24}$')
    kind: Literal['arithmetic', 'other', 'unreadable']
    location: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=300)
    student_answer: str | None = Field(max_length=300)
    verdict: Literal['correct', 'incorrect', 'uncertain']
    basis: str = Field(min_length=1, max_length=300)
    calculation: Calculation | None = None

    def validate_calculation(self):
        if self.kind == 'unreadable' and self.verdict != 'uncertain':
            raise ImageReviewProtocolError('unreadable_requires_uncertainty', self.location)
        if self.kind == 'arithmetic' and self.calculation is None:
            raise ImageReviewProtocolError('arithmetic_requires_transcribed_calculation', self.location)
        if self.calculation is not None:
            correct = self.calculation.correct()
            expected = 'correct' if correct else 'incorrect'
            if self.verdict not in (expected, 'uncertain'):
                raise ImageReviewProtocolError('calculation_verdict_mismatch', self.location)


class ImageReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conclusion: Literal['all_correct', 'some_incorrect', 'uncertain', 'not_checking']
    scope: Literal['all_visible', 'specified'] = 'specified'
    coverage: Literal['complete', 'partial']
    questions: list[QuestionReview] = Field(max_length=80)

    def supported_conclusion(self):
        if self.conclusion == 'not_checking' and self.questions:
            raise ImageReviewProtocolError('not_checking_cannot_include_grading_claims')
        if self.conclusion != 'not_checking' and not self.questions:
            raise ImageReviewProtocolError('image_review_questions_required')
        if len({(q.image_ref, q.location) for q in self.questions}) != len(self.questions):
            raise ImageReviewProtocolError('duplicate_image_review_question')
        if self.conclusion == 'all_correct' and (
            self.coverage != 'complete' or any(q.verdict != 'correct' for q in self.questions)
        ):
            raise ImageReviewProtocolError('all_correct_requires_complete_correct_evidence')
        if self.conclusion == 'some_incorrect' and not any(q.verdict == 'incorrect' for q in self.questions):
            raise ImageReviewProtocolError('incorrect_claim_requires_question_evidence')
        return self


def reconcile_calculations(report: ImageReview) -> ImageReview:
    """Recompute only explicitly transcribed arithmetic; never infer image text.

    Pixel transcription and coverage still require the independent visual judge.
    Uncertain readings remain uncertain, even if their possible numbers agree.
    """
    questions = []
    verdict_changed = False
    for question in report.questions:
        if question.calculation is not None and question.verdict != 'uncertain':
            verdict = 'correct' if question.calculation.correct() else 'incorrect'
            if verdict != question.verdict:
                verdict_changed = True
            # The calculator establishes final-value correctness only. A model's
            # unverified diagnosis of an intermediate step is not calculator evidence.
            question = question.model_copy(update={
                'verdict': verdict,
                'basis': '仅复算转写原式与最终作答，未核验中间步骤',
            })
        questions.append(question)
    conclusion = report.conclusion
    if verdict_changed and any(question.verdict == 'incorrect' for question in questions):
        conclusion = 'some_incorrect'
    elif verdict_changed and report.coverage == 'complete' and all(question.verdict == 'correct' for question in questions):
        conclusion = 'all_correct'
    elif verdict_changed:
        conclusion = 'uncertain'
    return ImageReview.model_validate({**report.model_dump(), 'questions': questions, 'conclusion': conclusion})


def validate_image_review(candidate, images: list[str | None]) -> None:
    refs = {image_ref(value) for value in images if value}
    if not refs:
        return
    if candidate.work is not None and candidate.image_review is None:
        raise ImageReviewProtocolError('image_review_required_for_image_work')
    report = candidate.image_review
    if report is None:
        return
    report.supported_conclusion()
    for question in report.questions:
        question.validate_calculation()
    if any(q.image_ref not in refs for q in report.questions):
        raise ImageReviewProtocolError('image_review_references_unselected_image')
    if report.conclusion == 'all_correct' and {q.image_ref for q in report.questions} != refs:
        raise ImageReviewProtocolError('all_correct_requires_every_selected_image')


def review_problem(summary: str | None, candidate, images: list[str]) -> str | None:
    if not images:
        return summary
    try:
        body = json.loads(summary or '{}')
    except ValueError:
        body = {'protected_problem_context': summary}
    if not isinstance(body, dict):
        body = {'protected_problem_context': body}
    body['selected_image_refs'] = list(dict.fromkeys(image_ref(value) for value in images))
    body['image_review'] = candidate.image_review.model_dump(mode='json') if candidate.image_review else None
    return json.dumps(body, ensure_ascii=False)


def require_configuration(bundle: dict) -> None:
    """Deployment capability handshake; the marker is a protocol ID, not semantics."""
    for filename in ('agents/tutoring.turn.json', 'agents/tutoring.image-target.json',
                     'gates/tutoring.leak-judge.json'):
        prompt = bundle['files'][filename]['prompt']['template']
        if '[image-review.v1]' not in prompt:
            raise ValueError(f'{filename}: Admin发布尚未声明image-review.v1，先发布已验证的配置再部署，保留当前服务')
