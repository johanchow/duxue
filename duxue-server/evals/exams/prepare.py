"""Fetch the exact PDFs used to build the Beijing question map."""

import argparse
import json
import os
import tempfile
from pathlib import Path

import httpx
import pymupdf

from .papers import SOURCES, tasks
from .transport import digest


def verify(path, ref):
    if digest(path) != ref["sha256"]:
        raise ValueError(f"Unexpected PDF bytes: {path}")
    with pymupdf.open(path) as doc:
        if len(doc) != ref["pages"]:
            raise ValueError(f"Page count mismatch: {path}")


def prepare(root, download):
    refs = json.loads(Path(__file__).with_name("sources.json").read_text())
    for s in SOURCES:
        for role, ref in refs[s].items():
            dest = root / s / (role + ".pdf")
            if not dest.exists() and download:
                dest.parent.mkdir(exist_ok=True, parents=True)
                with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as f:
                    tmp = Path(f.name)
                try:
                    with httpx.stream(
                        "GET", ref["url"], follow_redirects=True, timeout=60
                    ) as res:
                        res.raise_for_status()
                        with tmp.open("wb") as output:
                            for chunk in res.iter_bytes():
                                output.write(chunk)
                    verify(tmp, ref)
                    os.replace(tmp, dest)
                finally:
                    tmp.unlink(missing_ok=True)
            verify(dest, ref)
        for _, _, first, last in tasks(s):
            if not 1 <= first <= last <= refs[s]["paper"]["pages"] or last - first >= 4:
                raise ValueError(f"Invalid question page span in {s}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    prepare(args.data, args.download)
