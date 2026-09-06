---
name: domain-driven-design
description: Design or review complex business software with Domain-Driven Design. Use for subdomains, bounded contexts, aggregates, domain services, domain events, application-layer CQRS, context integration, or DDD-oriented technical design documents. Do not use for simple CRUD work with no meaningful business invariants.
metadata:
  version: "2.0.0"
  short-description: DDD domains, aggregates, CQRS, and contracts
---

# Domain-Driven Design

Use DDD to align software boundaries with business language and invariants. Start
with the problem space—subdomains and ubiquitous language—before choosing
aggregates, repositories, CQRS, or deployment boundaries. Apply tactical DDD only
where business complexity warrants it; simple CRUD modules may remain simple.

## Non-negotiable layer boundaries

Keep these concerns distinct in both designs and code:

| Layer | Owns | Does not own |
|---|---|---|
| Domain | Aggregates, entities, value objects, invariants, domain services, domain events | HTTP, ORM, transactions, prompt/model calls, query DTOs |
| Application | Commands, use cases, authorization, transaction boundaries, aggregate loading/saving, event publication | Domain rules or direct persistence details |
| Query / CQRS | Read models, projections, query services, response DTOs | Aggregate mutation or write-side invariants |
| Interface / Infrastructure | API/SSE adapters, repositories, Outbox, workers, database and external-system adapters | Business-policy decisions |

An aggregate is a transactional consistency boundary, not a module or table. The
aggregate root is the only external mutation entry point. Keep aggregates small,
reference other aggregates by ID, and use events for consistency outside the
aggregate.

Commands, application services, queries, and APIs are **not members of an
aggregate**. They belong to the application and interface layers of the bounded
context that owns the use case.

## Design workflow

### 1. Establish the domain map

Before modeling objects, produce a Domain Inventory containing **N named domains**.
For each, record:

- subdomain type: core, supporting, or generic;
- bounded context name and its ubiquitous language;
- owner and responsibility;
- upstream and downstream contexts;
- integration style: published language, ACL, customer-supplier, partnership, or
  separate ways.

Do not equate a database table, a microservice, an AI agent, or a UI page with a
bounded context without evidence of a distinct model and language. A modular
monolith can host many bounded contexts.

Use an Event Storming-style chain to validate the model:

```text
Actor → Command → Aggregate behavior / invariant → Domain Event → Read Model
```

Name commands as imperatives (`ConfirmPlan`), domain events in past tense
(`PlanConfirmed`), and queries as questions (`GetTodayPlan`). Flag missing
business decisions, ambiguous terms, and cross-context handoffs before coding.

### 2. Design every bounded context

For each bounded context, document the following in this order:

1. **Boundary and language** — responsibility, non-goals, terms, upstream and
   downstream contracts.
2. **Domain model** — aggregates, entities, value objects, invariants,
   repositories, factories where needed, domain services, and domain events.
3. **Application use cases** — command handlers/use cases and their transaction
   boundary, authorization, aggregates loaded, domain methods called, persisted
   events, idempotency key, and failure behavior.
4. **CQRS query model** — projections, consistency expectation, query signatures,
   and response DTOs. A projection may combine data for a screen but must not
   become a write aggregate.
5. **Interface contracts** — API or internal message signatures, authorization,
   validation errors, and streaming/event contracts where applicable.
6. **Infrastructure mapping** — repository implementation, database tables,
   Outbox, worker/consumer, and observability. Keep this mapping separate from
   domain behavior.

Read [the design template](references/ddd-design-template.md) when creating or
substantially restructuring a DDD technical design document.

### 2.1 Add visual design evidence when relationships need it

Use diagrams to make ownership, boundaries, consistency, and lifecycle visible.
Keep diagram source version-controlled and use the repository's established
diagram format/tool. Diagrams complement normative tables and contracts; they
never replace API signatures, field schemas, authorization rules, or invariants.

At the system level, distinguish these two diagrams:

- **DDD Context Map** — shows every bounded context, Core/Supporting/Generic
  classification, business ownership, upstream/downstream direction, and the
  integration contract (published event, API, ACL, or Process Manager). It does
  not show databases, queues, controllers, or deployment topology.
- **Layered Architecture Map** — shows dependency direction across interface,
  application, domain-context modules, and infrastructure/runtime. It may show
  clients, APIs, workers, repositories, Outbox, and storage, but it must not
  replace the Context Map's ownership semantics.

Within a bounded context, choose the smallest diagrams that establish the needed
facts:

| Diagram | Use when | Must show | Must not show |
|---|---|---|---|
| Aggregate Map | The context has two or more write aggregates, or one aggregate coordinates with another | Aggregate roots, ID/event references, write vs projection models, strong vs eventual consistency | ORM joins or direct object references across aggregates |
| Aggregate Internal UML | An aggregate owns child entities/value objects or has non-obvious composition | Root, each child entity identity and key attributes, value-object fields, multiplicity, mutating behaviors and invariant owner | API DTOs, repository implementations, ORM annotations, other aggregate objects |
| State Diagram | An aggregate has non-trivial lifecycle/status transitions | States, commands/events that trigger transitions, terminal/recoverable paths | Low-level persistence transitions |
| Command–Event–Projection Flow | A command uses Outbox, worker, asynchronous projection, or CQRS | Actor, command, application service, aggregate, domain/integration event, projection, consistency point | Model hidden reasoning or unrelated infrastructure |
| Event Choreography / Saga Flow | A business outcome spans bounded contexts | Event owner, consumer, local transaction, compensation/reconciliation | A fictitious global transaction |
| Request Sequence Diagram | API/SSE/Agent calls have meaningful sync/async or resume behavior | Caller, adapter, application service, domain port, async return/continuation | Every internal method call |

Minimum evidence rules:

- With two or more bounded contexts, provide one Context Map. Add a Layered
  Architecture Map when runtime/layer dependencies are part of the decision.
- With two or more write aggregates in a context, provide an Aggregate Map.
- When an aggregate owns a child entity, or an invariant depends on relations among
  internal objects, add both an **Aggregate Internal UML** and an **Entity
  Inventory**. A simple root with only self-contained value objects may omit them,
  but state the reason explicitly.
- Add a State Diagram for any non-trivial lifecycle and a Command–Event–Projection
  Flow for any eventually consistent command path.
- Add Event Choreography when one business outcome crosses contexts.
- When no diagram is needed, state the reason rather than creating decorative
  diagrams.

### 3. Design command and query sides correctly

For the command side, an application service normally:

1. authorizes the actor and validates the command shape;
2. opens the transaction and loads one aggregate through its repository;
3. invokes domain behavior or a domain service;
4. saves the aggregate and persists its domain events atomically;
5. publishes an integration event through an Outbox when another context must
   react.

Do not let a command handler mutate another bounded context's aggregate directly.
If a strict invariant appears to require that, reconsider the aggregate/context
boundary. Otherwise use eventual consistency, an integration event, and where
needed a Process Manager / Saga for the multi-step workflow.

For the query side:

- queries do not mutate aggregates;
- read models may be denormalized and eventually consistent;
- cross-context views are assembled from published projections or an explicit
  query/BFF layer, never by exposing another context's aggregate internals;
- state the freshness guarantee of every material view.

CQRS does not require Event Sourcing. Use an immutable fact ledger or event store
only when the domain needs replay/audit semantics; do not label ordinary audit
records as Event Sourcing.

### 4. Integrate bounded contexts explicitly

Within a bounded context, domain events express facts meaningful to that domain.
Across contexts, translate only stable facts into published/integration events.
Specify event owner, schema version, idempotency key, ordering assumption,
consumer behavior, retry policy, and dead-letter/reconciliation path.

Use an Anti-Corruption Layer when an external or upstream model would pollute the
local language. AI runtimes, LLM tools, and external APIs are adapters: they may
propose data, but domain/application rules validate it before it changes business
state. An Agent Coordinator is normally an application-level Process Manager, not
automatically a bounded context or aggregate.

## Required delivery

When asked to design or review a DDD system, return:

1. the Domain Inventory and Context Map;
2. one Aggregate Card for every write aggregate;
3. one Entity Inventory for every non-trivial aggregate: each entity/value object
   has its identity (if any), key domain attributes, domain behaviors, and its
   responsibility for invariants; this is a design contract, not an ORM field list;
4. one Use-case Card for every command;
5. query models and their freshness/consistency rules;
6. public/internal API or message signatures;
7. cross-context event contracts and failure handling;
8. the diagrams required by the visual-evidence rules, with their source paths;
9. testable invariants and acceptance scenarios.

For a review, identify missing ownership, mixed layers, aggregate-boundary
violations, direct cross-context writes, accidental Event Sourcing, and query
models used as write models. Recommend the smallest change that repairs each
issue.

## Practical guardrails

- Prefer a rich domain model only for real invariants; avoid ceremonial entities,
  repositories, or events for simple CRUD.
- Domain services are stateless domain logic that belongs to neither one entity
  nor one value object. They do not manage HTTP, transactions, or persistence.
- Use a repository per aggregate root, not per table. Its interface is a domain
  port; its ORM/database implementation is infrastructure.
- A domain event is not a log line, model trace, or transport retry record.
- Never expose ORM models, aggregate internals, or raw event payloads as public
  API contracts.
- Keep terminology singular and owned: one concept has one definition within a
  bounded context; different contexts may intentionally translate it.
- In an Entity Inventory, list only state and methods that participate in domain
  decisions: identity, lifecycle, policy evaluation, or invariant enforcement.
  Do not mechanically mirror database columns, getters/setters, DTO fields, or
  persistence helpers.
- A child entity needs its own identity only when the aggregate must distinguish
  it over time. Otherwise prefer an immutable value object. Show this distinction
  in the Internal UML and explain which object owns each cross-object invariant.
