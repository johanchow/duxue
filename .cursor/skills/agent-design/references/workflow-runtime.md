# Stateful Workflow and Hybrid Runtime

Read this reference only for a workflow or hybrid that persists state, waits for
an actor or external event, resumes after a delay, or performs a material action
through a resumable lifecycle.

## Stable execution scope

Persist an immutable `ExecutionScope` when the run starts. It contains the
values needed to interpret later transitions consistently:

| Field class | Examples |
|---|---|
| Actor and authorization | actor identity, grants, role, tenant or visibility scope |
| Target | object/reference scope and allowed target set |
| Interpretation basis | locale, timezone, calendar, policy version when relevant |
| Concurrency | input/object versions and correlation/idempotency references |
| Runtime compatibility | workflow and checkpoint schema versions |

Prompts, transcripts, and scratchpads are not substitutes for this scope. A
resume reads it; it must not recompute changing values such as current time,
date, target selection, or permissions.

## Lifecycle and resume

Define a finite state model with ownership, allowed transitions, timeout,
cancellation, and terminal states. Before every resume, perform deterministic
preflight checks for:

1. checkpoint existence and ownership;
2. workflow/checkpoint schema compatibility;
3. execution-scope and authorization consistency;
4. input, target, and concurrency-version validity; and
5. the expected waiting state and action binding.

Do not enter the graph/runtime if preflight fails. Return a defined conflict or
recovery outcome instead. Specify whether a waiting run may cross a time or
policy boundary, and whether it must expire, migrate, or restart.

## Approval and resumable actions

Use an issued capability for a material action. In addition to the general
actor, operation, target/version, expiry, and idempotency bindings, a resumable
capability binds `run_id`, checkpoint reference, workflow-state version, and
the expected wait state. Record issuance, consumption, expiry, and replay
behavior. Revalidate domain preconditions immediately before the side effect.

## Failure and caller recovery

For each transition define the transport result, runtime state, safe visible
message, retryability, and caller recovery action. Distinguish at least:

| Outcome | Typical caller action |
|---|---|
| conflict or stale capability | discard local action and refresh authoritative state |
| missing/incompatible checkpoint | restart or regenerate the review; do not resume blindly |
| retryable execution failure | offer a bounded explicit retry |
| non-retryable failure | close/escalate or require a new run |
| confirmed side effect | return the authoritative committed result, idempotently |

Never encode a failed transition as a successful transport response with no
actionable outcome.

## Workflow review additions

- [ ] ExecutionScope has an authority, schema version, lifecycle, and allowed writers.
- [ ] State transitions, waits, cancellation, expiry, and terminal states are explicit.
- [ ] Resume preflight prevents entering an absent, incompatible, stale, or wrong wait state.
- [ ] Resumable capabilities bind the run/checkpoint/state and have consumption/replay semantics.
- [ ] Tests cover stale/replayed actions, concurrent state change, missing/incompatible checkpoints, cancellation, timeout, and relevant time/locale boundaries.
