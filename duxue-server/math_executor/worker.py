"""Isolated child entrypoint: resource limits precede parsing and SymPy import."""

import os
import resource
import runpy
import sys
from pathlib import Path

resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_FSIZE, (32768, 32768))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
if os.uname().sysname == "Linux":
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
runpy.run_module("math_executor.engine", run_name="__main__")
