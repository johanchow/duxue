"""按教学卡里的已确认原文点读。请求不能另带一段要合成的文字。"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.application.workflows.pronunciation_guidance import (
    SUPPORTED_RATES,
    lesson_view,
    unpack_lesson_items,
)
from app.infrastructure.ai.aliyun_tts import AliyunSpeechSynthesizer, SpeechSynthesisError
from app.infrastructure.persistence.models import PronunciationLesson


def canonical_rate(value: float) -> float | None:
    for rate in SUPPORTED_RATES:
        if abs(rate - value) < 1e-6:
            return rate
    return None


class PronunciationLessonQuery:
    def __init__(self, db: Session, synthesizer: AliyunSpeechSynthesizer | None = None):
        self.db = db
        self.synthesizer = synthesizer or AliyunSpeechSynthesizer()

    def get(self, *, ward_id: str, lesson_ref: str) -> dict:
        row, index = self._owned(ward_id, lesson_ref)
        return lesson_view(row, index=index)

    def speak(self, *, ward_id: str, lesson_ref: str, rate: float) -> bytes:
        row, index = self._owned(ward_id, lesson_ref)
        item = lesson_view(row, index=index)
        playback = canonical_rate(rate)
        if playback is None:
            raise HTTPException(400, "unsupported speech rate")
        try:
            return self.synthesizer.synthesize(text=item["source_text"], locale=item["locale"], rate=playback)
        except SpeechSynthesisError as error:
            raise HTTPException(503, {"code": "tts_error", "reason": error.code}) from error

    def _owned(self, ward_id: str, lesson_ref: str) -> tuple[PronunciationLesson, int]:
        base_ref, sep, raw_index = lesson_ref.partition(":")
        if sep and not raw_index.isdigit():
            raise HTTPException(404, "pronunciation lesson not found")
        index = int(raw_index) if sep else 0
        row = self.db.get(PronunciationLesson, base_ref)
        if row is None or row.ward_id != ward_id or row.speech_ref != base_ref:
            raise HTTPException(404, "pronunciation lesson not found")
        items = unpack_lesson_items(row)
        if index < 0 or index >= len(items):
            raise HTTPException(404, "pronunciation lesson not found")
        return row, index
