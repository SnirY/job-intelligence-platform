# Coding Standards, Testing Strategy & Codex Working Rules

## Source-of-truth order

1. Product and architecture docs in `/docs`
2. ADRs
3. Existing domain contracts
4. Tests describing intended behavior
5. Existing implementation

If code and docs conflict, investigate rather than assuming either is automatically correct.

## Codex execution workflow

```text
Understand
↓
Inspect
↓
Plan
↓
Implement
↓
Test
↓
Review
↓
Report
```

## Before coding

Read:

- task
- relevant docs
- relevant code
- relevant tests
- recent ADRs

Inspect for existing services, entities, components, utilities, and patterns before creating new ones.

## Scope discipline

Implement the smallest coherent change.

Do not expand scope with unrelated:

- libraries
- refactors
- abstractions
- features

Adjacent low-risk cleanup is acceptable when useful and tested.

## Architecture boundaries

```text
API
↓
Application
↓
Domain
↓
Infrastructure
```

### API layer

Only:

- authentication context
- request validation
- use-case invocation
- response mapping

### Application layer

Orchestrates use cases.

### Domain layer

Owns:

- business rules
- scoring
- state transitions
- truth validation
- domain entities

### Infrastructure layer

Implements:

- repositories
- provider adapters
- storage
- queues
- external fetching

## No God Services

Do not create a giant all-purpose service.

Prefer focused services such as:

- JobIngestionService
- MatchEngine
- ResumeStrategyService
- ApplicationTrackingService

## Backend standards

Use:

- Python type annotations
- clear exceptions
- Pydantic at boundaries
- typed internal models

Avoid untyped `dict[str, Any]` between important layers.

## Database standards

Every schema change requires a migration.

Keep complex queries in repositories or query services.

Do not silently delete user history to simplify development.

## Frontend standards

Use:

- strict TypeScript
- typed API responses
- feature-level organization
- reusable design-system components
- accessible interactions

Avoid giant 1,500-line page components.

## Server state

Use TanStack Query or equivalent for API state.

Do not duplicate server responses into global state without a reason.

## Design system

Reuse:

- tokens
- buttons
- cards
- badges
- metrics
- panels
- chart patterns
- loading/error states

## AI code standards

Never call LLM providers directly from:

- controllers
- React components
- repositories

All calls go through the AI abstraction.

Prompts are versioned and centrally managed.

AI output is untrusted until schema and business validation pass.

## AI failure handling

Handle:

- timeout
- rate limit
- provider error
- invalid output
- business-validation failure

Never silently swallow failure.

Never return fake intelligence when AI fails.

## AI cost discipline

Before a model call ask:

- Do we already have a valid result?
- Did the input change?
- Can deterministic logic handle this?
- Can a smaller model handle this?

## Matching standards

Core scoring must be deterministic and testable without live AI.

Do not change the scoring formula silently.

Every match result needs requirement-level traceability.

## Resume standards

Do not rewrite the entire resume in one opaque call.

Required workflow:

```text
Strategy
↓
Suggestions
↓
Truth Validation
↓
User Review
↓
Version
```

## History

Do not mutate past:

- used resume versions
- historical matches
- historical analyses
- application events

## Application status

Every status update must also create history, ideally in one transaction.

## Background tasks

Tasks should be:

- retry-safe
- observable
- idempotent where practical
- associated with an entity

Failure must not delete the underlying resource.

## Logging

Use structured logs with useful correlation fields.

Do not log:

- full resume text
- authentication tokens
- API keys
- unnecessary personal details

## Testing philosophy

Protect:

- behavior
- business rules
- data integrity
- contracts

Use:

```text
Many Unit Tests
Moderate Integration Tests
Focused E2E Tests
```

## Unit-test priorities

- matching scoring
- requirement weighting
- application transitions
- truth validation
- gap calculations
- recommendation rules

## Integration-test priorities

- repositories
- database transactions
- API endpoints
- worker boundaries
- storage adapters

## E2E priorities

- onboarding
- add job
- analyze job
- view match
- prepare resume
- track application

## AI tests

Normal tests should not make random live AI calls.

Use:

- fake providers
- recorded fixtures
- stubbed structured responses

Maintain a separate evaluation suite under `tests/evals/`.

## Golden AI cases

Include fixtures for:

- Junior Java Backend
- Junior Python Backend
- Computer Vision
- Full Stack
- Ambiguous Seniority

## Regression rule

Every significant bug should get a regression test.

## Security tests

At minimum verify:

- User A cannot access User B job
- User A cannot download User B resume
- private-network URL fetching is blocked
- unsupported uploads are rejected

## CI

Run:

- formatting
- lint
- type checks
- unit tests
- integration tests
- frontend build
- backend checks
- migrations from clean database

## Definition of Done

A feature is complete only when:

- behavior is implemented
- persistence works
- API contract is complete
- UI states are handled
- tests exist
- errors are handled
- no fake production behavior remains
- relevant docs/tracking are updated

AI features also require:

- prompt version
- output schema
- validation
- failure state
- traceability
- evaluation fixture

## Review checklist

Before finishing:

- Does it match the task?
- Does it preserve boundaries?
- Is logic duplicated?
- Are error paths handled?
- Are writes safe?
- Is ownership enforced?
- Are tests sufficient?
- Did complexity grow unnecessarily?

## Security-first rules

Never trust:

- client user IDs
- uploaded filenames
- external URLs
- AI output
- browser-supplied ownership

## Dependencies

Before adding a dependency ask:

- Is it necessary?
- Is it maintained?
- Can existing tools solve it?
- What operational cost does it add?

## Refactoring

Large refactors need:

- clear motivation
- explicit scope
- tests protecting behavior

## Commits

Prefer coherent, reviewable commits.

Suggested format:

```text
feat(jobs): add pasted-description job creation
fix(matching): prevent preferred skills from becoming blockers
test(resume): add unsupported metric regression case
```

## Reporting

At the end of meaningful work, Codex must report:

- what changed
- why
- tests run
- known limitations
- remaining work

Do not claim completion when work is partial.

## Tracking

Development tracking is part of repository maintenance and Definition of Done.

Relevant files must reflect actual project state.

## Final principles

```text
Read before writing.
Understand before refactoring.
Build complete vertical slices.
Preserve data integrity.
Treat AI output as untrusted.
Test important behavior.
Do not fake completion.
Prefer incremental changes.
Document meaningful decisions.
```
