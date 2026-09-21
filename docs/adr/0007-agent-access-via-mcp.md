# ADR-0007 — Agent access over MCP, above the API rather than inside it

Status:
Proposed

Date:
2026-08-23

Relates to:
ADR-0001 (package boundaries), ADR-0004 and ADR-0005 (identity). Prompted by
the career-ops comparison.

## Context

`santifer/career-ops` solves this platform's problem as a pack of Markdown
prompt files executed by whatever AI coding CLI the user already has. It has
67,000 stars and no server. The comparison raised a fair question: should an AI
agent be able to drive this platform too, and if so, does that mean adopting
something like their shape?

The two halves of the answer point in opposite directions, which is why this
needs a decision rather than a task.

**Why they put logic in Markdown.** They have no API. In career-ops the agent
*is* the engine — the scoring rules live in `modes/_shared.md` because there is
nowhere else for them to live. That is a coherent design for a local, serverless,
single-user tool, and it costs them reproducibility: their own documentation
describes scoring as "holistic judgement... no arithmetic formula".

**Why we should not.** We have 101 typed endpoints, `packages/shared-types`, a
deterministic matcher, and `truth.py`. Moving any decision into prompt text
would trade the one property no competitor has for a convenience.

But the underlying want is legitimate. Driving this platform through a browser
is fine for reviewing a match and poor for "save these six postings, analyse
them, and tell me which two are worth my evening". That is agent work, and the
API can already express all of it.

**The blocker is authentication.** `infrastructure/auth/oidc.py` verifies RS256
session tokens against a published JWKS. That is the right design for a browser
session and unusable for a program: an agent has no browser, no login, and no
way to obtain such a token. A search of the API found no API-key or
personal-access-token path — the only keys present are the AI provider's. There
is currently no way for any non-browser client to authenticate at all.

## Decision

**Expose the platform to agents as an MCP server that sits above the HTTP API,
and add a scoped machine credential to reach it. Move no logic.**

### The server

```text
apps/mcp/       a thin MCP server; no business logic
                speaks HTTP to the existing /api/v1
```

A separate application in `apps/`, not a package and not a mode of the API. It
holds no domain code, no database session, and no model call. It is a translation
layer, and if it ever needs to decide something, that decision belongs in the
API instead.

It talks to the API over HTTP rather than importing the application layer
in-process. That is deliberate. In-process access would let a tool reach past
the route layer to a use case directly, bypassing authorization and the
`UserOwnedMixin` scoping that every route currently enforces. The network hop
buys a boundary that cannot be forgotten.

### The tools

Tools map to what a person does, not to what the code contains:
`save_job`, `analyze_job`, `get_match`, `list_gaps`, `tailor_resume`,
`list_applications`. Their schemas are generated from the OpenAPI document
FastAPI already emits, so a contract change surfaces as a schema change rather
than as drift.

Read tools and write tools stay distinct, and the write set stays small.

### The credential

A scoped personal access token, verified alongside OIDC rather than instead of
it. `TokenVerifier` is already a Protocol with a single `verify` method
returning `VerifiedIdentity` — ADR-0005 made authentication provider-neutral,
and this is the first case that benefits. A second verifier implementation
satisfies the same Protocol, and the application layer never learns which one
answered.

Tokens are user-issued, revocable, scoped to a permission set, and stored
hashed. Scope is per token, and the default scope is read-only.

### The rule that makes all of this safe

> The agent gets to drive. It does not get to decide.

Every guarantee already in the system continues to hold underneath, because
none of them live at this layer:

- The matcher stays deterministic Python. No tool can produce a verdict.
- `truth.py` still blocks a fabricated figure, whoever requested the rewrite.
- AI proposals still land in a review table that only a person clears.
- Application events remain append-only.

This is `docs/05`'s second principle — AI never controls verified facts —
applied to a new caller rather than restated for one.

## Consequences

**A security property, not merely a design preference.** A prompt injection
carried inside a job posting reaches career-ops' engine directly, because the
engine is a model reading text. Their mitigation is a written rule that scraped
content is data and never instructions — a good rule, and one made of the same
material an attacker is writing in. Against an MCP surface over this API, an
injected posting can at worst cause an unnecessary API call. It cannot alter a
verdict or introduce a fact, because neither is decided at the layer it reached.

**A new authentication surface, and it is the real cost.** A long-lived bearer
token is a weaker credential than a short session token, and the mitigations —
hashing at rest, scopes, revocation, expiry, rate limits, an audit trail of token
use — are the work. This is the part of the ADR to review hardest.

**Write scope needs care.** `tailor_resume` spends money and `save_job` creates
rows. Cost control and idempotency are not afterthoughts here, and destructive
operations are simply absent from the tool set.

**A second client of the API contract.** Today the web app is the only consumer,
so a route change is caught by TypeScript. An MCP server is a second consumer,
and generating from OpenAPI is what keeps that from becoming a maintenance tax.

**It does not help adoption.** career-ops' distribution advantage comes from
`npx` and no server. This changes nothing about that, and should not be argued
for on those grounds.

## Alternatives Considered

**Adopt career-ops' shape — logic in Markdown, executed by a CLI.**
Rejected. It would move the matcher inside a model and forfeit reproducibility,
auditability and the evidence chain — everything this platform is for. Their
design is right for a serverless local tool and wrong for a system whose
premise is that a verdict must be re-derivable.

**An MCP server importing the application layer in-process.**
Rejected. Faster and simpler, and it removes the authorization boundary. A tool
calling a use case directly is one refactor away from skipping the ownership
check that only the route enforced.

**Let an agent use a session token.**
Rejected. It requires a human browser login to start, expires quickly, and
cannot be scoped or revoked independently. Tokens minted for a browser should
not be reused as machine credentials.

**A CLI instead of MCP.**
Reasonable and narrower, and it would still need the same credential. MCP is
preferred because tool schemas and a typed contract are exactly what this API
already has to offer, and because it works across agents rather than one.

**Do nothing.**
The honest default while Phase 11 is open. Nothing here is urgent, and the
credential work is real. This ADR is Proposed for that reason: the decision is
worth having written down before it is needed, and worth revisiting only once
Phase 12, job discovery, makes bulk operations
common enough for driving by hand to become the bottleneck.
