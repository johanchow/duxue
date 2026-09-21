# Agent Design Decision Framework

Use this guide to choose the smallest architecture that meets the requirement.
It is framework-neutral: a graph library, agent SDK, queue, or memory store does
not settle these decisions by itself.

## Is an agent necessary?

Use ordinary software or a single structured model call when the request has a
known sequence, limited ambiguity, and no need to choose tools adaptively. Use
an agentic design only when task quality depends on iterative interpretation,
planning, observation, correction, or tool selection in a changing environment.
State the measurable benefit that justifies its extra cost and variability.

## Who controls the flow?

| Condition | Preferred control model |
|---|---|
| Ordered stages, fixed policy, regulated actions, or known completion criteria | Deterministic workflow/state machine controlled by code |
| One bounded ambiguity inside a known flow | Fixed workflow with a structured model node |
| Open-ended exploration or tool choice with safe, measurable completion | Bounded agent loop controlled by a runtime |
| Both fixed lifecycle and local adaptive reasoning | Hybrid: code controls stages; an agent controls only designated stages |

An agent loop needs explicit stop conditions and budgets. A planner may propose a
plan, but code must validate permissions, constraints, and state transitions.

## Minimum safeguards by control model

Apply the smallest row that covers the design; a hybrid needs both its workflow
and loop safeguards.

| Safeguard | Stateless structured call | Fixed workflow | Bounded agent loop | Hybrid |
|---|---:|---:|---:|---:|
| Structured proposal and deterministic validation | Required when output affects decisions | Required | Required | Required |
| Explicit outcome/error/recovery contract | Required | Required | Required | Required |
| Approval capability for material side effects | When applicable | When applicable | When applicable | When applicable |
| Persistent execution scope | Usually not needed | Required if multi-step or delayed | Required if resumable/long-running | Required |
| Checkpoint and resume preflight | No | Required if resumable | Required if resumable | Required if resumable |
| Loop budget, stop condition, completion validator | No | No | Required | Required for loop stages |

An approval capability normally binds the actor, operation, target and target
version, expiry, and idempotency key. See [workflow runtime](workflow-runtime.md)
for the additional requirements of resumable work, and
[agent-loop runtime](agent-loop-runtime.md) for loop-stage controls.

## What is a step?

Classify each step rather than treating all work as an agent action:

- **Deterministic function/service:** validation, authorization, calculation,
  persistence, policy enforcement, and irreversible actions.
- **Model call:** extraction, classification, synthesis, explanation, or a
  structured proposal.
- **Tool call:** a capability boundary from the runtime to an external or domain
  system; it requires schema, permission, and failure semantics.
- **Agent loop:** repeated model/tool observation under a budget and runtime
  control.
- **Workflow/graph transition:** a durable orchestration decision across steps,
  user waits, time, or failure.

## How should state be separated?

- Business facts are authoritative domain data and change only through governed
  business transactions.
- Runtime state records the run, current phase, budgets, and checkpoints needed
  for recovery.
- Working context is a bounded, assembled view for the current decision; it is
  not automatically durable truth.
- Durable memory is sourced, scoped, correctable, expirable knowledge retained
  for future work.
- Trace/audit data proves what happened and supports diagnosis; it is not a
  control plane or prompt store by default.

Never let a model-written summary silently become an authoritative fact or a
long-lived memory without defined validation and provenance.

For a stateful run, use the execution-scope rules in
[workflow runtime](workflow-runtime.md); a stateless call does not need to
invent persistent run state.

## How should tools be designed?

Expose tools by task and permission, not as an unbounded catalog. Each tool
should have a clear name, narrow purpose, typed inputs and outputs, examples or
descriptions sufficient for model selection, authorization, timeout, rate/cost
limit, observability, and predictable errors. Read and write capabilities should
be visibly distinct. Use idempotency and propose/confirm execution for material
side effects.

Prefer typed observation enums over prose-only errors. A loop should be able to
branch on results such as `unique`, `ambiguous`, `no_match`, `needs_input`,
`changed`, `rejected`, `stale`, and `tool_error` without asking the model to
reverse-engineer state from natural language. If the next safe action depends
on a distinction, make that distinction part of the tool contract.

Treat retrieved content and tool output as untrusted input: it may be incorrect,
stale, malicious, or contain instructions that conflict with system policy.

## How should semantic changes be resolved?

Let the model interpret open-ended language and emit a typed candidate, not an
authoritative identifier or write command. Runtime code resolves the candidate
only within the actor's authorized objects and applies a mutation only after a
unique match and validation. If matching is ambiguous, request a constrained
choice. If it finds no match, do not infer that creation is intended: require an
explicit create proposal or actor choice. Keywords and regexes may validate a
known field format, but are not a substitute for semantic intent resolution.

Do not manufacture a clarification from an empty candidate set. A constrained
choice requires choices; without them, return `no_match`, `not_editable`, or a
similar typed observation and let the loop decide whether another explicit user
proposal can proceed independently.

## When should agents be split?

Keep a single agent when one coherent instruction set, context, permission set,
and evaluation can handle the task. Split only when doing so creates a testable
improvement through one or more of:

- independently owned responsibility or policy;
- materially different context or data access;
- least-privilege tool/permission isolation;
- an independently measurable specialized capability;
- parallel, genuinely independent work.

For a central user experience, prefer a manager that delegates bounded tasks and
retains final authority. Use explicit handoff only when ownership of the ongoing
interaction genuinely transfers. Do not use free-form shared scratchpads as the
integration mechanism.

## How should components communicate?

Use governed shared state for authoritative data with a clear owner and
concurrency control. Use direct request/response for immediate bounded work. Use
durable events for facts that other components may process asynchronously; define
schema versions, correlation, deduplication, ordering, retry, and reconciliation.
Messages carry a minimum context reference or scoped artifact, not unrestricted
private reasoning or an entire conversation history.

## What warrants human approval?

Require approval or an equivalent deterministic policy decision before actions
that are irreversible, high-impact, externally visible, financially meaningful,
privacy-sensitive, privileged, or difficult to explain/reverse. Show the actor
what will happen, preserve the approval decision, and revalidate at execution if
the underlying state may have changed.
