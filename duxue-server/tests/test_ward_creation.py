"""Ward creation must satisfy PostgreSQL's immediate FK checks."""
from __future__ import annotations

import unittest

from app.dependencies import Principal
from app.main import create_ward
from app.models import GuardianWard, Ward
from app.schemas import WardCreate


class _Db:
    def __init__(self): self.added = []; self.flushes = 0
    def add(self, value): self.added.append(value)
    def flush(self): self.flushes += 1
    def commit(self): pass
    def refresh(self, value): pass


class WardCreationTest(unittest.TestCase):
    def test_flushes_ward_before_adding_guardian_relation(self):
        db = _Db()
        create_ward(WardCreate(display_name="小读"), Principal("guardian", "tenant", "admin"), db)
        relation_index = next(i for i, value in enumerate(db.added) if isinstance(value, GuardianWard))
        self.assertIsInstance(db.added[relation_index - 1], Ward)
        self.assertEqual(db.flushes, 2, "ward must be flushed before its FK relation is added")
