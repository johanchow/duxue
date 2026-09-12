# Duxue observability deployment

The server exports OTLP/HTTP directly to the endpoint in its standard
`OTEL_EXPORTER_OTLP_*` variables. This works with Grafana Cloud and with an
authenticated private Grafana Alloy gateway; this repository intentionally
does not contain any endpoint or credential.

## Required deployment settings

Set these values in the server's production environment (not Git):

- `OTEL_SERVICE_NAME=duxue-server`
- `OTEL_EXPORTER_OTLP_ENDPOINT`: Grafana Cloud gateway or private Alloy OTLP
  base endpoint.
- `OTEL_EXPORTER_OTLP_HEADERS`: the authorization header required by that
  endpoint.
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_TRACES_SAMPLER=parentbased_traceidratio`
- `OTEL_TRACES_SAMPLER_ARG=0.2` in production; use `1.0` temporarily when
  debugging a bounded incident.

`api`, `worker`, and `beat` set `OTEL_SERVICE_COMPONENT` in Compose. Keep this
dimension rather than creating distinct service names so cross-process views
stay grouped under `duxue-server`.

## Grafana import and alerts

Import `grafana/dashboards/duxue-server.json` into a Grafana instance whose
Prometheus-compatible datasource UID is `prometheus`; change that UID in the
files if your datasource has another name. Provision or import
`grafana/alerts/duxue-server.yaml` after adapting the contact point and folder
to your Grafana installation.

The dashboard is intentionally limited to low-cardinality labels. Search
Tempo by `service.name=duxue-server`, then use `agent.run_id` / `agent.thread_id`
on a selected trace; do not turn either field into a metric label.

## Agent debug audit

Normal OTLP spans and container logs contain hashes, length and outcome only.
To enable an emergency, short-lived audit file, set both
`AGENT_DEBUG_AUDIT_ENABLED=true` and `AGENT_DEBUG_AUDIT_PATH` to a mounted,
encrypted, access-controlled path. It writes a 160-character excerpt with
email and mainland phone redaction only, so it still requires a child-data
approval and a retention job. Never point it at stdout, Loki, or the source
tree.
