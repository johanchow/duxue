"""Low-cardinality operational measurements, with no evidence or user content."""

from opentelemetry import metrics

meter = metrics.get_meter("duxue.observation")
jobs = meter.create_counter("duxue.observation.jobs", unit="1")
latency = meter.create_histogram("duxue.observation.latency", unit="s")
images = meter.create_counter("duxue.observation.images", unit="1")


def record_job(kind, result, seconds):
    attributes = {"kind": kind, "result": result}
    jobs.add(1, attributes)
    latency.record(max(0, seconds), {**attributes, "stage": "execution"})


def record_lag(stage, seconds):
    latency.record(max(0, seconds), {"stage": stage})
