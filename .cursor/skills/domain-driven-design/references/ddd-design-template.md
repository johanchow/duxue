# DDD Design Deliverable Template

Use this template when producing a new design or substantially restructuring an
existing DDD design. Omit sections that are genuinely inapplicable and state why;
do not invent aggregates or CQRS solely to fill a template.

## 1. Domain Inventory and Context Map

| # | Domain / subdomain | Type | Bounded context | Owns | Upstream / downstream | Integration |
|---|---|---|---|---|---|---|
| 1 | `<name>` | Core / Supporting / Generic | `<context>` | `<business responsibility>` | `<contexts>` | `<pattern + contract>` |

```text
<Upstream Context> -- <Published Event / ACL / API> --> <Downstream Context>
```

Define the ubiquitous language that differs across contexts. State explicitly
which context owns each mutable business concept.

### Global visual evidence

- Context Map source and path:
- Layered Architecture Map source and path, or reason it is unnecessary:

The Context Map documents business ownership and context integration. The Layered
Architecture Map documents Interface → Application → Domain ports and
Infrastructure adapter dependency direction; do not combine the two into an
unreadable all-in-one diagram. It is required when persistence, asynchronous
processing, external adapters, or runtime/layer dependencies are material.

## 2. Bounded Context: `<name>`

### Boundary

- Responsibility:
- Non-goals:
- Upstream contracts consumed:
- Downstream contracts published:
- Ubiquitous language:

### Domain model

#### Aggregate Map

- Diagram source and path, or reason it is unnecessary:
- Write aggregates and their aggregate roots:
- ID/event references between aggregates:
- Strong-consistency boundaries and eventual-consistency paths:

#### Aggregate: `<AggregateRoot>`

- Identity:
- Entities owned by the aggregate:
- Value objects:
- Invariants enforced atomically:
- Public domain behaviors:
- Domain events raised:
- References to other aggregates (IDs only):
- Repository port:

#### Entity Inventory (required for a non-trivial aggregate)

| Object | Kind | Identity | Key domain attributes | Public domain behaviors | Invariant responsibility |
|---|---|---|---|---|---|
| `<AggregateRoot>` | Aggregate root | `<id>` | `<only decision-relevant state>` | `<verbs, not CRUD setters>` | `<what it enforces atomically>` |
| `<ChildEntity>` | Entity | `<local identity / composite identity>` | `<key state>` | `<verbs>` | `<its local rule, or “owned by root”>` |
| `<ValueObject>` | Value object | None | `<immutable fields>` | `<validation / calculation>` | `<valid construction rule>` |

Do not turn this into an ORM schema. Include only state and methods that affect a
domain decision, lifecycle, or invariant. Omit the table only for a simple root
whose composition is fully clear from its Aggregate Card, and state why.

#### Aggregate Internal UML

- Diagram source and path, or reason it is unnecessary:
- Match the Entity Inventory: root, child entity identities/key attributes,
  value-object fields, multiplicity, mutating behaviors, and invariant owner.
  Exclude DTOs, ORM annotations, repositories, and foreign aggregate objects.

#### Lifecycle State Diagram

- Diagram source and path, or reason the lifecycle is trivial:
- States, transition command/event, guards, and terminal/recoverable states:

#### Domain service: `<name>`

- Required only when this business rule belongs to no single aggregate.
- Inputs / outputs:
- Rule implemented:
- Does not own transactions, authorization, or transport.

### Application use cases

#### State-change trigger matrix

Complete one row for every material state-changing Use Case. A cross-context
event is received by an Infrastructure consumer adapter, then interpreted by the
receiving context's Use Case; it never calls the producer's Aggregate directly.

| Trigger and source | Interface / entrypoint | Receiving Use Case or Process Manager | Aggregate / domain method | Local domain event | Outbox, projection, or next local action | Consistency, idempotency, failure/reconciliation |
|---|---|---|---|---|---|---|
| `<actor intent / scheduler / callback / EventName.v1>` | `<interface / worker / consumer adapter>` | `<UseCase / ProcessManager>` | `<Root.method() / DomainService>` | `<LocalPastTenseEvent>` | `<outbox / view / none>` | `<local transaction / key / retry or compensation>` |

- State whether the trigger is synchronous, locally deferred, or cross-context.
- For a strong local invariant, show the synchronous Application-to-Domain call;
  do not introduce an event solely as a stylistic relay.
- For an asynchronous or cross-context write path, provide a Trigger →
  Interface → Use Case / Process Manager → Domain → Event/Projection sequence
  diagram and participant inventory.

#### `<UseCaseName>`

```python
class <UseCaseName>Input(BaseModel):
    actor_id: UUID
    aggregate_id: UUID
    idempotency_key: str
    # intent fields
```

- Actor and authorization rule:
- Trigger and adapter/entrypoint:
- For an inbound event: schema/version validation, idempotency key, and ACL mapping:
- Preconditions:
- Transaction boundary:
- Aggregate loaded and method invoked:
- Domain service used, if any:
- Persisted domain events / published integration events:
- Idempotency behavior:
- Expected failures and user-safe result:
- Command–Event–Projection Flow source and path when projection is asynchronous:

#### Sequence Diagram Participant Inventory

| Participant | Canonical type | Owned responsibility |
|---|---|---|
| `<name>` | `<Actor / Interface / Use Case / Query / Process Manager / Aggregate Root / Entity / Value Object / Domain Service / Domain Event / Integration Event / Read Model / Projection / Infrastructure>` | `<responsibility>` |

### Query side / CQRS

#### `<ViewName>`

- Purpose and consumers:
- Source events / source tables:
- Fields and redaction policy:
- Freshness: strongly consistent / eventually consistent, with expected lag:

```python
class <QueryName>(BaseModel):
    actor_id: UUID
    # filters and pagination

class <ViewName>(BaseModel):
    # response-only fields
```

### Interface contracts

```text
POST /<resource>                 → <UseCaseName>
GET  /<resource>/{id}            → <QueryName> / <ViewName>
<Context>.<EventName>.v1         → published integration event
```

- Request/response schemas:
- Authorization:
- Validation and domain error mapping:
- Versioning and compatibility:

### Infrastructure mapping

Complete every subsection that applies. If one is not applicable, state why rather
than leaving it blank. This section maps the design to adapters and operations;
it must not redefine domain invariants.

#### Ports and adapters

| Port owned by Domain/Application | Concrete adapter | Protocol / dependency | Configuration / secret boundary | Timeout, retry, rate limit / circuit breaker | Error mapping / fallback |
|---|---|---|---|---|---|
| `<RepositoryPort or GatewayPort>` | `<adapter>` | `<database / HTTP / SDK / queue>` | `<configuration owner>` | `<policy or N/A with reason>` | `<domain-safe behavior>` |

Application and Domain code depend only on the port. The concrete adapter is
assembled at the composition root. State an Anti-Corruption Layer translation
when an upstream/external model differs from the local language.

#### Persistence and transaction

| Aggregate / projection | Repository / store | Tables, keys, indexes, and FK policy | Transaction owner and atomic writes | Schema migration / compatibility / rollback |
|---|---|---|---|---|
| `<AggregateRoot>` | `<RepositoryPort / adapter>` | `<physical mapping>` | `<Use Case>` | `<strategy>` |

- One repository port per aggregate root; projections use query/projection stores,
  never aggregate repositories for writes.
- State the idempotency constraint and where it is enforced.
- For a schema change, state migration order, compatibility window, backfill/rebuild
  and rollback or why those are unnecessary.

#### Async delivery and projections

| Event / job | Outbox / producer owner | Consumer adapter → receiving Use Case / projection | Idempotency key | Ordering and freshness | Retry, dead-letter, reconciliation, replay |
|---|---|---|---|---|---|
| `<EventName.v1>` | `<local transaction owner>` | `<consumer>` | `<key>` | `<assumption / lag>` | `<operational behavior>` |

If no asynchronous delivery exists, state that the use case remains synchronous
and why. An audit log, trace, or ordinary retry record is not automatically a
domain or integration event.

#### Security, data governance, and observability

| Concern | Boundary / mechanism | Redaction, retention, or deletion | Evidence / metric / alert |
|---|---|---|---|
| Authorization | `<principal and scope check>` | `<sensitive data rule>` | `<audit / metric>` |
| Secrets / external access | `<owner and injection mechanism>` | `<what must not be logged>` | `<failure signal>` |
| Trace and operations | `<correlation / trace propagation>` | `<audit retention>` | `<logs, metrics, SLO/alert>` |

### Acceptance scenarios

```gherkin
Given <domain state>
When <actor> invokes <use case>
Then <aggregate invariant/result>
And <domain event or read model outcome>
```

## 3. Cross-context workflow

Use this only when a business outcome spans contexts.

| Step | Owning context | Trigger / local Use Case / published event | Receiving Use Case | Consistency | Failure / compensation |
|---|---|---|---|---|---|
| 1 | `<context>` | `<use case/event>` | `<UseCase or N/A>` | Local transaction | `<behavior>` |

Document the Process Manager / Saga only when it owns real multi-step workflow
state. Do not use it as a generic event relay.

- Event Choreography / Saga Flow source and path when this workflow crosses
  contexts:
- Request Sequence Diagram source and path when API, SSE, or resume semantics
  are material to the workflow:
