# Bounded Agent Loop Runtime

Read this reference only for a design in which a runtime permits repeated
model/tool observation and action selection. A fixed workflow with one model
node does not need an agent loop.

## Loop contract

Define the loop's objective, allowed tools, permitted state writes, and
deterministic completion validator. A model's statement that work is complete
is a candidate; runtime code verifies completion before returning success or
performing a material side effect.

Set explicit maximums for iterations, model calls, tool calls, elapsed time,
tokens/cost, retries per tool, and delegation depth. Define a stop outcome for
each exhausted budget.

## Tool and observation design

Design the loop around a small set of reliable tools. "Small" means each tool
has one clear authority boundary, not that it hides many unrelated cases behind
free-form text. Prefer tools that model the domain decisions the loop actually
needs to make:

| Tool shape | Purpose | Typical observations |
|---|---|---|
| `Resolve*` | Bind a model-proposed reference within an authorized candidate set | `unique`, `ambiguous`, `no_match`, `unauthorized` |
| `Validate*` / `Evaluate*` | Check completeness, conflicts, policy, or readiness | `valid`, `needs_input`, `conflict`, `rejected` |
| `Apply*` / `Patch*` | Perform a governed, idempotent state change | `changed`, `no_op`, `stale`, `rejected`, `tool_error` |
| `Clarify*` / `IssueChoice*` | Create an actor-answerable wait point | `issued`, `not_answerable`, `expired` |
| `FinishLoop` | Return the typed loop outcome and operation report | `success`, `partial_success`, `needs_input`, `rejected`, `budget_exhausted`, `tool_error` |

Every observation must be a typed result with a safe summary, not just prose.
Use stable enums for control flow and structured fields for candidates,
conflicts, retryability, and caller recovery. The model may use prose to explain
an already-typed result, but prose must not be the only contract.

Do not collapse materially different observations into one generic failure.
For object references, distinguish at least:

- `unique`: exactly one authorized target was found, and the tool returns the
  stable reference the next tool may use.
- `ambiguous`: more than one authorized target was found, and the tool returns
  the non-empty choice set that an actor or later model step may disambiguate.
- `no_match`: no authorized target was found. This is not the same as
  ambiguity, and it must not silently become a create operation.
- `unauthorized` or `not_editable`: a target may exist, but the current actor or
  lifecycle cannot operate on it.

Only issue a clarification or choice tool when the runtime can provide a
non-empty, authorized, actor-answerable candidate set or a concrete missing
field. A state with no choices, no valid target, or no actionable recovery is a
typed rejection or failure observation, not a question.

Avoid both extremes: a huge "do everything" tool makes the loop opaque, while
many tiny format-only tools push domain state back into prompt glue. A good tool
is narrow in authority, complete in its local invariants, and reusable by tests
without the model.

## Per-iteration control

For every iteration record the observation source, selected action, tool result
summary, budget consumption, and stop reason. Tool output remains untrusted
input. Only validated observations may update durable runtime state; temporary
reasoning need not be persisted.

Restrict tools by stage and permission. A retry may address a transient tool
failure, but may not bypass validation, broaden authority, repeat an irreversible
effect, or continue after the stop budget.

## Loop review additions

- [ ] The loop has a deterministic completion validator and explicit non-success stop outcomes.
- [ ] Iteration, tool, time, token/cost, retry, and delegation budgets are enforced by runtime code.
- [ ] Each tool is stage-scoped, permission-checked, typed, observable, and has predictable retry semantics.
- [ ] Tool observations use stable enums that distinguish success, ambiguity, no-match, rejection/conflict, stale state, and tool failure where applicable.
- [ ] Actor-facing clarification is issued only for answerable states with a concrete missing field or non-empty authorized candidate set.
- [ ] Per-iteration trace data records action, result class, budget, and stop reason without retaining unnecessary private reasoning.
- [ ] Tests cover budget exhaustion, repeated tool failure, malformed/untrusted tool output, invalid completion claims, and cancellation.
