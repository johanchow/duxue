"""Bound the T2 fork independently of the time needed to deliver its result."""

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import nullcontext
from contextvars import copy_context
from time import monotonic

from app.agent_specs.execution_trace import Recorder, recorder
from app.infrastructure.ai.client import model_time_budget, remaining_model_time


def collect_solve_routes(targets, run):
    remaining = remaining_model_time()
    # Leave one third of the remaining turn for verification, explanation and review.
    # Standalone workers have no outer turn deadline.
    budget = min(60.0, remaining * 2 / 3) if remaining is not None else 60.0
    deadline = monotonic() + budget
    parent = recorder()
    children = {target: Recorder() for target in targets} if parent else {}

    def invoke(target):
        capture = children[target].capture() if parent else nullcontext()
        with capture, model_time_budget(max(0, deadline - monotonic())):
            remaining_model_time()
            value = run(target)
            remaining_model_time()
            return value

    pool = ThreadPoolExecutor(max_workers=len(targets))
    try:
        futures = {
            target: pool.submit(copy_context().run, invoke, target)
            for target in targets
        }
        done, _ = wait(futures.values(), timeout=max(0, deadline - monotonic()))
        results = {}
        for target, future in futures.items():
            if future not in done:
                continue
            if parent:
                parent.merge_child(children[target])
            try:
                results[target] = future.result()
            except TimeoutError:
                continue
        return results
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
