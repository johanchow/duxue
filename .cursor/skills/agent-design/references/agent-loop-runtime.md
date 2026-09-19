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
- [ ] Per-iteration trace data records action, result class, budget, and stop reason without retaining unnecessary private reasoning.
- [ ] Tests cover budget exhaustion, repeated tool failure, malformed/untrusted tool output, invalid completion claims, and cancellation.
