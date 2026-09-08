---
name: domain-driven-design
description: Design or review complex business software with Domain-Driven Design. Use for subdomains, bounded contexts, aggregates, domain services, domain events, application-layer CQRS, context integration, or DDD-oriented technical design documents. Do not use for simple CRUD work with no meaningful business invariants.
metadata:
  version: "2.2.0"
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
| Interface | HTTP/gRPC/SSE endpoints, message-consumer entrypoints, request/response DTOs, authentication adapters, transport error mapping | Use-case orchestration, domain rules, ORM/database access |
| Infrastructure | Repository and ORM implementations, database, cache, Outbox, workers, queues, model/tool/third-party adapters, logging/metrics/tracing | Domain policy, cross-context business decisions, public API DTOs |

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

Use a trigger-aware Event Storming-style chain to validate the model:

```text
Trigger → Interface / Infrastructure Adapter → Application Command or Event Handler
→ Aggregate behavior / invariant → Domain Event → Outbox / Projection
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
3. **Application use cases** — command handlers/use cases and their trigger,
   transaction boundary, authorization, aggregates loaded, domain methods called,
   persisted events, idempotency key, and failure behavior.
4. **CQRS query model** — projections, consistency expectation, query signatures,
   and response DTOs. A projection may combine data for a screen but must not
   become a write aggregate.
5. **Interface contracts** — API or internal message signatures, authorization,
   validation errors, and streaming/event contracts where applicable.
6. **Infrastructure mapping** — ports/adapters, persistence and transaction
   mapping, asynchronous delivery, external-dependency resilience, security/data
   governance, observability, and migration/recovery. Keep this mapping separate
   from domain behavior. State why a category is inapplicable rather than omitting
   it.

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
  Architecture Map when persistence, asynchronous processing, external adapters,
  or runtime/layer dependencies are material to the design.
- With two or more write aggregates in a context, provide an Aggregate Map.
- When an aggregate owns a child entity, or an invariant depends on relations among
  internal objects, add both an **Aggregate Internal UML** and an **Entity
  Inventory**. A simple root with only self-contained value objects may omit them,
  but state the reason explicitly.
- Add a State Diagram for any non-trivial lifecycle and a Command–Event–Projection
  Flow for any eventually consistent command path.
- Add Event Choreography when one business outcome crosses contexts.
- Add a Request Sequence Diagram when an API, SSE, model/tool/third-party call,
  or checkpoint/resume path has material success or failure behavior.
- Add a trigger-to-state-change sequence for a material asynchronous or
  cross-context write path. It must distinguish the transport adapter,
  Application handler, Aggregate/Domain Service, Domain Event, and Outbox or
  projection; do not leave a diagram that merely connects event names.
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

### 3.1 Make every state-change trigger explicit

For every material state transition, state the full causal path in a **Trigger →
Application → Domain → Event/Projection Matrix**. Do not list only a domain
method and an event without identifying who invokes the method and when.

| Trigger class | Entry and owner | Application responsibility | Domain action | Follow-up |
|---|---|---|---|---|
| User/API command | Interface controller/endpoint | Authorize, validate, open local transaction, invoke use case | Load root and call its behavior / a domain service | Persist domain events; publish only required stable integration facts |
| Scheduled or batch job | Scheduler/worker adapter | Start an idempotent command with a defined time/window | Invoke policy and aggregate behavior | Record checkpoint/result; retry or reconcile as specified |
| External callback | Webhook/SDK adapter | Authenticate/translate callback, deduplicate, invoke local command | Local aggregate behavior only | Persist local outcome and optionally publish integration event |
| Cross-context integration event | Consumer adapter then receiving-context Application Event Handler | Validate schema/version, deduplicate, apply ACL, authorize system actor, open local transaction, invoke a local command/use case | Receiving context's own aggregate/domain service | Persist local events; its subsequent publication is a new local decision |
| Same-context strongly consistent rule | Existing Application Service | Coordinate required roots in one local transaction | Directly call aggregate/domain-service behaviors | Do not introduce async indirection merely for event style |
| Same-context deferred reaction | Local event dispatcher/worker | Start a separately idempotent local use case after commit | Load and mutate local aggregate as needed | Outbox/job/retry policy and eventual-consistency statement |

The Infrastructure adapter **receives and reliably delivers** a transport message;
the receiving Application Event Handler **interprets it as a local command**.
An integration event must never invoke another context's aggregate method directly.
Likewise, a Domain Event is a local business fact, not a queue message, log entry,
or universal trigger: the Application layer decides whether it is persisted,
dispatched locally after commit, projected, or translated into a versioned
integration event.

Use direct synchronous domain calls when one local invariant requires atomic
consistency. Use an Outbox-backed integration event when a different bounded
context may react eventually. A Process Manager/Saga owns only genuine
multi-context workflow state; it is not a generic relay. For each asynchronous
reaction, document its new transaction, idempotency key, ordering assumption, and
failure/reconciliation behavior.

For the query side:

- queries do not mutate aggregates;
- read models may be denormalized and eventually consistent;
- cross-context views are assembled from published projections or an explicit
  query/BFF layer, never by exposing another context's aggregate internals;
- state the freshness guarantee of every material view.

CQRS does not require Event Sourcing. Use an immutable fact ledger or event store
only when the domain needs replay/audit semantics; do not label ordinary audit
records as Event Sourcing.

### 4. Specify infrastructure explicitly

For every bounded context with persistence, asynchronous processing, or an
external dependency, produce an **Infrastructure Design Card**. It is an
implementation contract for adapters and operational behavior, not a second
domain model. Include:

1. **Ports and adapters** — the owning Domain/Application port, concrete adapter,
   protocol/dependency, configuration/secrets boundary, timeout, retry, rate
   limit/circuit-breaker or explicit reason they do not apply, and error mapping.
2. **Persistence and transactions** — one repository port per aggregate root,
   tables/key constraints/indexes, transaction owner, atomic writes, migration
   compatibility, and rollback/backfill strategy where data changes.
3. **Async delivery and projections** — Outbox owner, event schema/version,
   consumer, idempotency key, ordering assumption, retry, dead-letter or
   reconciliation, replay/rebuild process, and read-model freshness.
4. **Security, data governance, and observability** — authorization boundary,
   secret handling, sensitive-data redaction, retention/deletion, correlation ID,
   audit trail, logs, metrics, alerts, and trace propagation.

An Application Service depends on repository, gateway, and publisher **ports**;
Infrastructure implements those ports and is assembled at the composition root.
Do not put ORM Sessions, concrete HTTP/SDK clients, queue clients, or prompt/model
calls inside aggregates or domain services. Existing code may have transitional
direct dependencies; document them as current implementation and state the target
port boundary instead of disguising them as domain behavior.

### 5. Integrate bounded contexts explicitly

Within a bounded context, domain events express facts meaningful to that domain.
Across contexts, translate only stable facts into published/integration events.
Specify event owner, schema version, idempotency key, ordering assumption,
consumer behavior, retry policy, and dead-letter/reconciliation path.

The published-event consumer belongs to the **receiving** bounded context. Its
adapter handles transport concerns; its Application Event Handler maps the
published language through an ACL where necessary and invokes a receiving-context
command. It does not share the producer's Aggregate, repository, transaction, or
domain vocabulary.

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
8. one Infrastructure Design Card for every context with persistence,
   asynchronous processing, or external dependencies;
9. the diagrams required by the visual-evidence rules, with their source paths;
10. a Trigger → Application → Domain → Event/Projection Matrix for every material
    write flow, plus a sequence diagram for each material asynchronous or
    cross-context state change;
11. testable invariants and acceptance scenarios, including failure/retry behavior
    where infrastructure is material.

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
- An application service may coordinate a transaction but should depend on
  repository, publisher, and external-service ports—not concrete ORM sessions,
  SDKs, HTTP clients, or queue clients. Assemble concrete adapters at the
  composition root.
- An Outbox, checkpoint, cache, trace, or audit record is infrastructure state;
  it does not become a domain event or aggregate merely because it is durable.
- External adapters must have an explicit bounded failure policy: timeout, retry
  eligibility, idempotency, error translation, and a user-safe fallback or
  escalation path. Do not let an unavailable provider silently decide business
  state.
- A domain event is not a log line, model trace, or transport retry record.
- Do not use an event as vague control flow. Name its owner, classify it as local
  Domain Event or cross-context Integration Event, and show the receiving
  Application handler and resulting local command. A transport consumer may not
  mutate an Aggregate by setting ORM fields directly.
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
