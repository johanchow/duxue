"""Keep all test state outside the worktree, regardless of import order."""

import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="duxue-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_root / 'test.db'}")
os.environ.setdefault("LOCAL_UPLOAD_DIR", str(_root / "uploads"))
os.environ.setdefault("SECRET_KEY", "test-secret")
