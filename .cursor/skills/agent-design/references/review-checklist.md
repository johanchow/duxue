# Agent Design Review Checklist

Mark every item pass, fail, or inapplicable with a reason.

## Purpose and control

- [ ] The user outcome, non-goals, risk tier, and measurable success criteria are explicit.
- [ ] The document explains why an agent is needed instead of a deterministic flow or one model call.
- [ ] The control model identifies which decisions belong to code and which are delegated to the model.
- [ ] Every loop, retry, and delegation has a bounded exit condition and budget.

## Contracts and state

- [ ] Material inputs, outputs, tool calls, events, and handoffs have schemas and validation owners.
- [ ] Business facts, runtime state, working context, durable memory, and trace data have separate owners and lifecycles.
- [ ] The model cannot directly create trusted facts, permissions, or durable writes without runtime/domain validation.
- [ ] Context has provenance, scope, freshness, and token/size bounds.

## Tools and collaboration

- [ ] Each tool has least privilege, authorization, typed parameters, safe errors, timeouts, and traceability.
- [ ] Material side effects are idempotent and use approval or propose/confirm controls where warranted.
- [ ] Multi-agent use has a concrete boundary and evaluation rationale; a simpler single-agent design was considered.
- [ ] Handoffs, shared facts, and events define authority, correlation, duplicate handling, and reconciliation.

## Reliability and safety

- [ ] Timeout, retry/backoff, cancellation, checkpoint/resume, partial failure, and model/tool outage behavior are defined.
- [ ] Concurrent execution and stale-state/version conflicts have a safe outcome.
- [ ] Prompt injection and untrusted retrieved/tool content are treated as security boundaries.
- [ ] Sensitive data access, retention, deletion, redaction, and audit requirements are addressed.
- [ ] An authorized actor or deterministic policy can halt, override, or escalate a run.

## Verification and delivery

- [ ] The design has unit, integration, failure/recovery, security, and end-to-end evaluation coverage appropriate to risk.
- [ ] Evaluation includes realistic success and adversarial/edge scenarios, not only happy paths.
- [ ] Trace fields, metrics, alerts, cost/latency budgets, and regression gates are specified.
- [ ] Rollout, rollback, migration, feature flag, and unresolved-risk plans are explicit where applicable.
