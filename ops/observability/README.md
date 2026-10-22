# Duxue observability deployment

Production Compose keeps the Server's existing direct OTLP export to Grafana.
Langfuse is an optional in-process span processor, not a gateway or a second
container:

```text
api / worker / beat -- OTLP --> Grafana (traces, metrics, logs)
                    \-- Langfuse SDK (approved AI traces only; optional)
```

This keeps local debugging and deployment unchanged: no collector service,
port, Compose override, or second environment file is needed.

## Required deployment settings

Set the following existing standard OTEL values in the deployment-only,
owner-readable `.env.prod`:

- `OTEL_SERVICE_NAME=duxue-server`
- `OTEL_EXPORTER_OTLP_ENDPOINT`: Grafana Cloud OTLP base endpoint.
- `OTEL_EXPORTER_OTLP_HEADERS`: the Grafana authorization header.
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_TRACES_SAMPLER=parentbased_traceidratio`
- `OTEL_TRACES_SAMPLER_ARG=0.2` in production; use `1.0` temporarily when
  debugging a bounded incident.

`api`, `worker`, and `beat` retain `OTEL_SERVICE_COMPONENT`; keep this dimension rather than
creating distinct service names so cross-process views stay grouped under
`duxue-server`.

The normal production command needs only this one environment file:

```bash
ENV_FILE=.env.prod docker compose up -d
```

## Optional Langfuse Cloud fan-out

Start the base deployment normally for Grafana only. To add Langfuse, create a
Langfuse account and project, then generate a **project API key pair** in that
project's settings. In the same deployment-only `.env.prod`, set:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Use the Langfuse region approved for your data residency requirements. The
public key is an identifier, but the secret key is a credential; never put
either in source code, the App, or CI logs.

The Langfuse configuration sends no logs or metrics. It exports only the
explicit `duxue.agent` turn, route, workflow, node, tool and check spans,
plus `duxue.model` `llm.request` generations. HTTP, SQL, Redis and Celery
instrumentation remains in Grafana only. A ConversationThread ID is the
Langfuse session ID, assigned before intent classification; the AgentRun ID
is trace/observation metadata for filtering one task execution. Exported
steps carry code-owned status categories and timing, never tool arguments or
results. Model calls carry component/version, model, operation, duration,
token counts, provider request ID and result status. Prompt text, Ward text,
model output, image/data URLs, SVG, ContextEnvelope, exception messages,
Authorization and API keys are excluded. Do not add prompt or completion
fields merely to improve the Langfuse UI.

Grafana and Langfuse share one OpenTelemetry sampler. To see every turn in a
Langfuse session, set `OTEL_TRACES_SAMPLER_ARG=1.0` in the deployment environment;
lower values omit whole turns from both destinations. Check the uncommitted
production `.env.prod` separately before deployment.

Langfuse is an observability aid, not a source of record or a permission to
upload children’s conversations. Dataset import, annotation, or any approved
sample export needs a separate child-data governance decision.

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
