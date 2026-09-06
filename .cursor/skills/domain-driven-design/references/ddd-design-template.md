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
Architecture Map documents code/runtime dependency direction; do not combine the
two into an unreadable all-in-one diagram.

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

### Command side / application use cases

#### `<CommandName>`

```python
class <CommandName>(BaseModel):
    actor_id: UUID
    aggregate_id: UUID
    idempotency_key: str
    # intent fields
```

- Actor and authorization rule:
- Preconditions:
- Transaction boundary:
- Aggregate loaded and method invoked:
- Domain service used, if any:
- Persisted domain events / published integration events:
- Idempotency behavior:
- Expected failures and user-safe result:
- Command–Event–Projection Flow source and path when projection is asynchronous:

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
POST /<resource>                 → <CommandName>
GET  /<resource>/{id}            → <QueryName> / <ViewName>
<Context>.<EventName>.v1         → published integration event
```

- Request/response schemas:
- Authorization:
- Validation and domain error mapping:
- Versioning and compatibility:

### Infrastructure mapping

- Repository adapter and persistence mapping:
- Transactional Outbox / worker / projection consumer:
- Idempotency constraint:
- Trace, audit, metrics, and retention requirements:

### Acceptance scenarios

```gherkin
Given <domain state>
When <actor> sends <command>
Then <aggregate invariant/result>
And <domain event or read model outcome>
```

## 3. Cross-context workflow

Use this only when a business outcome spans contexts.

| Step | Owning context | Command / event | Consistency | Failure / compensation |
|---|---|---|---|---|
| 1 | `<context>` | `<command/event>` | Local transaction | `<behavior>` |

Document the Process Manager / Saga only when it owns real multi-step workflow
state. Do not use it as a generic event relay.

- Event Choreography / Saga Flow source and path when this workflow crosses
  contexts:
- Request Sequence Diagram source and path when API, SSE, or resume semantics
  are material to the workflow:
