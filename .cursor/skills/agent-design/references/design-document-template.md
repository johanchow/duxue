# Agent Technical Design Template

Use the sections that materially affect the design. For an omitted section,
state why it is inapplicable. Keep business-domain design in its own source of
truth; this document defines the agent runtime's interaction with it.

## 1. Problem and boundaries

- User outcome and primary scenarios
- Scope, explicit non-goals, assumptions, and dependencies
- Risk tier: read-only, reversible write, irreversible/high-impact write, or
  regulated/sensitive action
- Success metrics: task quality, completion rate, safety, latency, and cost

## 2. Architecture decisions

| Decision | Chosen option | Reason | Rejected options | Verification |
|---|---|---|---|---|

Cover the need for an agent, control model, state persistence, tool exposure,
approval model, and whether multi-agent decomposition is justified.

For stateful workflows/hybrids, add the sections required by
[workflow runtime](workflow-runtime.md). For loops/hybrids, add the sections
required by [agent-loop runtime](agent-loop-runtime.md).

## 3. Components and authority

| Component | Responsibility | May decide | May read | May write/call | Must not do |
|---|---|---|---|---|---|

Separate the model/agent, deterministic runtime, domain/application services,
policy or authorization service, persistence, tool adapters, human actor, and
observability infrastructure as applicable.

## 4. Control flow and lifecycle

Describe the trigger, routing, execution loop, validation, completion, user
wait, cancellation, and error paths. Include a state diagram or sequence diagram
when any path is asynchronous, resumable, has external effects, or crosses a
component boundary.

| Node or transition | Controller | Input | Output | State change | Exit / failure condition |
|---|---|---|---|---|---|

State explicit bounds that apply to the chosen control model. See
[agent-loop runtime](agent-loop-runtime.md) for loop budgets and
[workflow runtime](workflow-runtime.md) for resume and recovery requirements.

## 5. Contracts

For each model call, tool, handoff, event, and public entry point, document a
versioned input/output schema, validation owner, error semantics, and backward
compatibility policy. Prefer structured outputs for data that drives a decision
or a side effect.

For model-proposed changes, include the candidate schema, authorized resolution
set, unique-match rule, ambiguity/no-match behavior, and the explicit condition
under which a new object may be created. For material actions, document the
issued capability and its actor, target/version, expiry, idempotency, and—when
resumable—run/checkpoint/state bindings.

## 6. State, context, memory, and audit data

| Data class | Authority | Allowed readers | Allowed writers | Retention / deletion | Model-direct mutation? |
|---|---|---|---|---|---|
| Business fact |  |  |  |  |  |
| Runtime/checkpoint state |  |  |  |  |  |
| Working context |  |  |  |  |  |
| Durable memory |  |  |  |  |  |
| Trace/audit record |  |  |  |  |  |

Describe context assembly, provenance, freshness, compaction, memory promotion,
correction, expiry, deletion, and user/tenant isolation as relevant.

For stateful execution, add the `ExecutionScope` and checkpoint rows required
by [workflow runtime](workflow-runtime.md).

## 7. Tools and side effects

| Tool or action | Purpose | Permission | Preconditions | Idempotency key | Confirmation | Failure / compensation |
|---|---|---|---|---|---|---|

State how tools are registered or selected, how schemas are validated, how
results are made useful to the model without leaking unnecessary data, and how
untrusted tool output is handled.

## 8. Collaboration and asynchronous processing

If using multiple agents, identify the unique reason for each boundary and its
single owner. Define whether messages are task handoffs, durable events, or
access to governed shared facts. Include handoff context, authority transfer,
correlation IDs, ordering assumptions, duplicate handling, and reconciliation.

## 9. Safety, security, and human control

Document data classification, prompt-injection defenses, tool-output trust
boundaries, authorization, least privilege, approval gates, escalation, stop
controls, and audit requirements. State the behavior on policy failure or low
confidence.

## 10. Reliability and operations

Define deadlines, retries/backoff, idempotency, deduplication, concurrency and
version-conflict handling, checkpoint/resume, partial failure, degradation when
model or tools are unavailable, and any compensation/reconciliation process.

Define a closed outcome taxonomy at least covering success, needs-input,
rejection/conflict, and execution failure. For each outcome state transport
semantics, safe user-facing content, retryability, and the caller's recovery
action. Do not use a successful transport response with an empty or
contradictory payload to represent failure. Add workflow-specific recovery
semantics only when [workflow runtime](workflow-runtime.md) applies.

## 11. Observability and evaluation

Specify trace correlation, logged decisions and tool calls, redaction, metrics,
alerts, and dashboards. Define offline scenarios and production metrics that
measure task success, policy violations, tool correctness, recovery, latency,
and cost. Include regression gates for prompts, models, tools, and policies.

Include invalid model structure and other general edge scenarios. Add lifecycle
or loop-specific scenarios only through the applicable mode reference.

## 12. Delivery plan

List incremental releases, feature flags, migration/backfill needs, rollback,
open risks, and ownership for unresolved decisions.
