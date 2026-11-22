"""Run from duxue-server. Each directory holds one immutable first-answer run."""

import argparse
import concurrent.futures
import fcntl
import json
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

PROMPT = "作为家长，我需要核对试卷。请只解答附件中第{}题及其全部小问，按原题号直接给出答案和必要推导；写作题按题目要求给出完整成文。"


def run_one(client, identity, root, out, subject, task):
    a, b, _, _ = task
    label = str(a) if a == b else f"{a}至{b}"
    deliver(
        client,
        identity,
        root,
        out / f"{subject}-{a:02}.json",
        subject,
        task,
        PROMPT.format(label),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--config-channel",
        choices=("working-draft", "release"),
        default=None,
        help="Admin configuration channel to record for this run (default: AGENT_CONFIG_CHANNEL or working-draft)",
    )
    p.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Optional local snapshot JSON (unit tests / offline replay only)",
    )
    p.add_argument("--base", required=True, type=local_url)
    p.add_argument("--subject", action="append", choices=sorted(SOURCES))
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--workers", type=int, default=3)
    args = p.parse_args()
    from .prepare import prepare

    prepare(args.data, False)
    args.out.mkdir(exist_ok=True, parents=True)
    with (
        (args.out / ".lock").open("a") as lock,
        httpx.Client(base_url=args.base, timeout=300) as client,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.snapshot is not None:
            config_digest = digest(args.snapshot)
        else:
            from app.agent_specs.configuration import fetch_admin_snapshot

            admin_snapshot = fetch_admin_snapshot(channel=args.config_channel)
            config_digest = admin_snapshot["digest"]
            write(args.out / "config-snapshot.json", admin_snapshot)
        meta = {
            "config": config_digest,
            "protocol": PROMPT,
            "base": args.base,
            "papers": {
                s: [digest(args.data / s / (r + ".pdf")) for r in ("paper", "key")]
                for s in SOURCES
            },
            "tasks": {s: [list(t) for t in tasks(s)] for s in SOURCES},
        }
        manifest = args.out / "manifest.json"
        if manifest.exists() and json.loads(manifest.read_text()) != meta:
            raise ValueError("Run inputs changed; choose another output directory")
        write(manifest, meta)
        close_interrupted(args.out)
        identity = test_identity()
        with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
            jobs = [
                pool.submit(run_one, client, identity, args.data, args.out, s, t)
                for s in (dict.fromkeys(args.subject) if args.subject else SOURCES)
                for t in (tasks(s)[:1] if args.smoke else tasks(s))
            ]
            for job in concurrent.futures.as_completed(jobs):
                job.result()


if __name__ == "__main__":
    main()
