"""One separate, disclosed delivery retry after a timeout or product fallback."""

import argparse
import concurrent.futures
import fcntl
import json
import re
import time
from pathlib import Path

import httpx

from .papers import SOURCES, tasks
from .transport import (
    close_interrupted,
    deliver,
    digest,
    local_url,
    test_identity,
    write,
)


def question_y(page, number):
    """Locate a printed question label at the left margin. Keep the page if uncertain."""
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if line["bbox"][0] > 100:
                continue
            text = "".join(span["text"] for span in line["spans"]).strip()
            if re.match(rf"^{number}(?:[.．](?!\d)|\s+[\u3400-\u9fff])", text):
                return line["bbox"][1]
    return None


def fragments(doc, s, task):
    a, b, first, last = task
    slices = []
    for i in range(first - 1, last):
        page = doc[i]
        rect = page.rect
        # Materials for reading and geography can precede numbered prompts.
        if s not in ("chinese", "english", "geography"):
            if i == first - 1:
                y = question_y(page, a)
                if y is not None:
                    rect.y0 = max(rect.y0, y - 12)
            if i == last - 1:
                y = question_y(page, b + 1)
                if y is not None:
                    rect.y1 = min(rect.y1, y - 3)
        if rect.height > 20:
            slices.append((i, rect))
    return slices


def submit(client, root, out, subject, task, identity):
    a, b, _, _ = task
    label = str(a) if a == b else f"{a}至{b}"
    prompt = f"请完成第{label}题全部小问，按题号给出最终答案。客观题直接列答案，解答题写必要步骤，作文交付全文。"
    deliver(
        client,
        identity,
        root,
        out / f"{subject}-{a:02}.json",
        subject,
        task,
        prompt,
        fragments,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(exist_ok=True, parents=True)
    identity = test_identity()
    with (
        (args.out / ".lock").open("a") as lock,
        httpx.Client(
            base_url=local_url(
                json.loads((args.run / "manifest.json").read_text())["base"]
            ),
            timeout=300,
        ) as client,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parent = digest(args.run / "manifest.json")
        manifest = args.out / "manifest.json"
        if (
            manifest.exists()
            and json.loads(manifest.read_text())["first_run"] != parent
        ):
            raise ValueError("different parent run")
        write(
            manifest,
            {"first_run": parent, "protocol": "one cropped retry after no answer"},
        )
        close_interrupted(args.out)
        while True:
            ready = []
            pending = False
            for s in SOURCES:
                for task in tasks(s):
                    name = f"{s}-{task[0]:02}.json"
                    dest = args.out / name
                    if dest.exists():
                        continue
                    src = args.run / name
                    row = json.loads(src.read_text()) if src.exists() else {}
                    if row.get("status") in (None, "submitted"):
                        pending = True
                    elif (
                        row.get("status")
                        in ("http_error", "transport_error", "delivery_unknown")
                        or row.get("answer", {}).get("act") == "unavailable"
                    ):
                        ready.append((s, task))
                    else:
                        write(dest, row)
            with concurrent.futures.ThreadPoolExecutor(5) as pool:
                jobs = [
                    pool.submit(submit, client, args.data, args.out, s, t, identity)
                    for s, t in ready
                ]
                for job in concurrent.futures.as_completed(jobs):
                    job.result()
            if not pending:
                return
            time.sleep(10)


if __name__ == "__main__":
    main()
