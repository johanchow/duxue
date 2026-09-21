---
name: agent-design
description: Design or review reliable LLM agent systems and their technical design documents. Use for systems involving agent loops, tool use, workflows or graphs, state and memory, long-running execution, human approval, or multi-agent coordination. Do not use for a single stateless model call or ordinary non-agent application design.
---

# Agent Design

Produce an implementable, reviewable design for an agentic capability. Treat an
agent as a bounded runtime component, not as a substitute for application
architecture, domain rules, authorization, or reliability engineering.

## Design principles

- Start from the user outcome, operating constraints, risk level, and measurable
  success criteria. Do not introduce an agent merely because an LLM is available.
- Keep deterministic work deterministic. Business invariants, authorization,
  durable writes, policy enforcement, and externally visible side effects belong
  to code and governed services.
- Give the model only the authority necessary for uncertain work: understanding,
  synthesis, bounded planning, or selecting among allowed actions. A model may
  propose structured changes; trusted runtime code validates and applies them.
- Prefer the smallest controllable composition: one model call, then a fixed
  workflow, then one bounded agent loop. Split into multiple agents only for a
  demonstrated boundary in responsibility, context, tools, permission, or
  evaluation.
- Use an agent loop to choose among reliable capabilities, not to replace
  domain checks. Tools should return typed observations such as `unique`,
  `ambiguous`, `no_match`, `rejected`, `changed`, or `needs_input`; the model
  decides the next allowed action from those observations.
- Make state ownership explicit. Do not use one mutable prompt, transcript, or
  scratchpad as a substitute for business data, durable runtime state, long-term
  memory, and audit evidence.
- Treat model outputs that identify or mutate business objects as untrusted
  semantic candidates. Resolve them only within an authorized candidate set;
  apply a mutation only after a unique, deterministic resolution. Ambiguity or
  a failed resolution must not silently become object creation or a different
  mutation.
- Never issue an actor-facing clarification for a state the actor cannot answer.
  For example, an empty authorized candidate set is a `no_match/rejected`
  observation, not a multiple-choice question with no choices.
- Give every externally visible result an honest outcome. Do not represent a
  rejected, failed, or incomplete operation as a successful response with an
  empty or contradictory payload. Define a machine-readable outcome, safe user
  message, and recovery action for each material failure.
- Design for interruption and failure before adding autonomy. Every material
  side effect needs an owner, authorization path, timeout, idempotency/retry
  behavior, and an observable outcome.

## Mode-aware requirements

Apply the shared safeguards to every mode. Then load only the reference that
matches the selected control model:

- **Any model-assisted mode:** use structured proposals for decisions that can
  affect facts or side effects; keep semantic interpretation with the model and
  deterministic validation, authorization, uniqueness, and persistence in
  code. Regexes and keywords may validate known formats, but must not be the
  primary interpreter of open-ended user intent.
- **Material approval or action:** issue a server-controlled capability bound
  to actor, operation, target/version, expiry, and idempotency. For resumable
  workflows, apply the additional bindings in the workflow reference.

Use [the decision framework](references/decision-framework.md) to select a
mode. For a stateful workflow or hybrid, read
[workflow runtime](references/workflow-runtime.md). For a bounded loop or
hybrid, read [agent-loop runtime](references/agent-loop-runtime.md). This avoids
imposing checkpoint or loop machinery on a stateless structured call.

## Workflow

1. Inspect the target project's architecture, domain model, data governance,
   permissions, runtime conventions, and existing interfaces. State assumptions
   and unresolved constraints instead of inventing them.
2. Define the problem, actors, scope, non-goals, risk tier, and acceptance
   metrics. Decide whether an agent is warranted.
3. Choose the control model using [the decision framework](references/decision-framework.md):
   fixed workflow, bounded agent loop, or a hybrid. Record rejected alternatives.
4. Specify the control flow and every material node. Include inputs, outputs,
   authority, allowed calls, durable state transitions, exit conditions, normal
   and failure paths, and the client or caller recovery action.
5. Define data boundaries: business facts, runtime/checkpoint state, working
   context, durable memory, and trace/audit data. Assign one authoritative owner
   and allowed writers for each.
6. Define tool contracts and side-effect controls. Design multi-agent handoffs or
   event communication only when the chosen decomposition requires them.
7. Complete reliability, security, observability, evaluation, rollout, and
   fallback design. Use [the document template](references/design-document-template.md)
   for a substantial design.
8. Before delivery, apply [the review checklist](references/review-checklist.md).
   Mark items inapplicable with a reason; do not silently omit them.

## Required design evidence

For each material decision, give the decision, reason, rejected alternative,
owner, and verification method. Use schemas/tables for contracts and a state or
sequence diagram when lifecycle, async behavior, handoff, or recovery would be
ambiguous in prose. Diagrams complement contracts; they never replace them.

Do not claim reliability from a framework name. State concrete limits: turn and
tool budgets, deadlines, validation, retry rules, checkpoint cadence, and who
can stop or override a run.

When changing an existing system, distinguish verified current behavior from the
target design and identify migration or backward-compatibility boundaries.
