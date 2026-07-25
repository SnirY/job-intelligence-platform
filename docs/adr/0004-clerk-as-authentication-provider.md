# ADR-0004 — Clerk as the authentication provider

Status:
Accepted

Date:
2026-07-25

Amended by:
ADR-0005, which renames the schema column, settings, and verifier type to be
provider-neutral. The decision to use Clerk stands; only the naming and the
uniqueness constraint changed. Where this document says `clerk_user_id`,
`JIP_CLERK_*`, or `ClerkTokenVerifier`, read `external_user_id`, `JIP_AUTH_*`,
and `JwksTokenVerifier`.

## Context

Phase 1 delivers sign up, login, logout, protected routes, and user scoping.
Two constraints come from the architecture documents and one from the stack.

`docs/04-system-architecture.md`:

> Use a managed provider rather than building authentication from scratch.
> The system must remain multi-user ready from day one.

`docs/10-api-contracts.md`:

> Backend resolves the authenticated user.
> Never accept a client-provided `user_id` as authorization.

The stack constraint is the harder one. Authentication has to serve two runtimes
that share no process and no session store: a Next.js app running in the
browser, and a FastAPI service running in Python. Most managed providers are
built around a JavaScript application and treat a separate backend as a
secondary concern. Whatever is chosen has to give the browser a real session
*and* give Python something it can verify on its own, without a network call to
the provider on every request.

This decision also reaches further than most. Once identity exists, every
user-owned table carries a foreign key derived from it and every query enforces
ownership through it. Changing providers later is a data migration, not a
dependency swap — which is why the shape of the internal user record matters
more here than the choice of vendor.

## Decision

Use **Clerk** as the authentication provider.

### Integration between Next.js and FastAPI

Clerk owns the browser session. FastAPI never talks to Clerk during a request.

```text
Browser
  └─ Clerk session (managed by @clerk/nextjs)
       └─ getToken() → short-lived RS256 JWT
            └─ Authorization: Bearer <jwt> → FastAPI
                 └─ verify signature against cached JWKS
                      └─ resolve internal User
```

Frontend:

- `@clerk/nextjs` with `<ClerkProvider>` in the root layout.
- `clerkMiddleware()` for route protection. **On Next.js 15 this file is
  `middleware.ts`**; Next.js 16 renames it to `proxy.ts`. The repository is on
  Next 15.5, so `middleware.ts` is correct today and is an item for the Next 16
  upgrade.
- No route is protected by default — protection is opt-in, so the middleware
  matcher must be written deliberately rather than assumed.
- `apps/web/src/lib/api.ts` gains a token per request. It must call `getToken()`
  on **each** call rather than caching the result: Clerk session tokens are
  deliberately short-lived, and a cached token starts returning 401 shortly
  after it is obtained.

Backend:

- A `get_current_user()` FastAPI dependency extracts the bearer token, verifies
  it, resolves the internal user, and returns it.
- Verification is offline. The API holds no Clerk credential and makes no
  outbound call to Clerk per request — only a periodic JWKS refresh.

The browser calls FastAPI directly rather than proxying through Next.js route
handlers. Proxying would add a hop and, worse, would recreate the API surface a
second time in TypeScript, leaving two places where the contract in
`docs/10-api-contracts.md` could drift.

### Internal user management

Clerk owns *identity*: credentials, email verification, MFA, account recovery.
The platform owns the *domain user*. These are separate records, joined by one
column.

```text
users
  id             uuid         primary key   -- internal; every foreign key points here
  clerk_user_id  text         unique, not null  -- the `sub` claim
  created_at     timestamptz  not null
  updated_at     timestamptz  not null
```

Two rules follow, and both matter more than they look:

1. **No table ever references `clerk_user_id`.** Every user-owned row carries a
   foreign key to `users.id`. The internal id is opaque and permanent; the
   Clerk id is a vendor detail. With this split, replacing the provider means
   rewriting one column in one table. Without it, it means rewriting every
   foreign key in the database.

2. **Profile data is not mirrored by default.** Email and name live at Clerk.
   Copying them into `users` creates a second source of truth that silently goes
   stale, and pulls PII into our database for no benefit. When a domain feature
   genuinely needs an attribute, copying it becomes a deliberate decision with a
   refresh story — not a default.

**Provisioning is just-in-time.** The first authenticated request for an unknown
`sub` creates the `users` row inside the auth dependency (find-or-create).
Webhook-driven creation was rejected for this: a `user.created` webhook races
the user's first request, and losing that race means a request arrives with a
valid token and no user row — an error path that exists only because of the
webhook.

Webhooks (Clerk delivers via Svix) are still worth adding later for
`user.deleted`, so account deletion at Clerk propagates into our data rather
than leaving orphaned rows. That is a Phase 11 / data-retention concern, not a
Phase 1 one.

**Ownership enforcement**: every user-owned query filters on the `users.id`
carried by `get_current_user()`. A `user_id` appearing in a path, query string,
or body is never an authorization input. `docs/11-engineering-standards.md`
requires a security test for this, and Phase 1 should add the first one — user A
cannot read user B's resource.

### JWT and JWKS verification

Clerk signs session tokens with **RS256** and publishes the public keys as a
JWKS document at the Frontend API URL:

```text
{issuer}/.well-known/jwks.json
```

Verification uses `pyjwt[crypto]` with `PyJWKClient`. Every one of the following
is checked, and a failure in any of them is a rejection:

| Check | Why it is not optional |
|---|---|
| `alg` pinned to RS256 | Accepting the token's own `alg` allows `none` and the RS256→HS256 confusion attack, where the public key is used as an HMAC secret |
| Signature against the JWKS key for the token's `kid` | The actual proof of authenticity |
| `exp` | An expired session must stop working |
| `nbf` | Rejects tokens presented before they are valid |
| `iss` | A correctly signed token from a *different* Clerk instance is still not ours |
| `azp` | Binds the token to our known origins; a token minted for another application of ours is not valid here |

Operational details:

- JWKS responses are cached and keyed by `kid`. An unknown `kid` triggers a
  refetch — but that refetch must be rate-limited, or an attacker can turn a
  stream of forged tokens with random `kid` values into a request flood against
  Clerk, and a self-inflicted outage when Clerk rate-limits us back.
- Clock-skew leeway stays small (a few seconds). Tokens are short-lived by
  design; generous leeway erodes exactly the property that makes them safe.
- Rejections surface as `401` with code `UNAUTHENTICATED` through the existing
  `APIError` machinery — the code is already mapped in
  `jip_api/core/errors.py`. The response must not explain *which* check failed;
  that only helps someone probing.

**The API needs no Clerk secret key.** JWKS is public, so verification requires
no credential at all. The API and worker images therefore carry no Clerk secret
— worth stating explicitly, because adding the secret key "just in case" would
quietly give away that property.

### Environment variables

Web (`apps/web/.env.local`, documented in `apps/web/.env.example`):

| Variable | Visibility | Purpose |
|---|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Public — inlined into the browser bundle | Identifies the Clerk instance (`pk_test_…` / `pk_live_…`) |
| `CLERK_SECRET_KEY` | **Server only** | Server-side Clerk calls (`sk_test_…` / `sk_live_…`) |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Public | Path to the sign-in page |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | Public | Path to the sign-up page |

`CLERK_SECRET_KEY` must never acquire a `NEXT_PUBLIC_` prefix. Next inlines
every `NEXT_PUBLIC_` value into the client bundle, so that single rename would
publish the secret to every visitor with no error, no warning, and nothing
visibly broken.

API (extends `jip_config.Settings`, `JIP_` prefix):

| Variable | Default | Purpose |
|---|---|---|
| `JIP_AUTH_ISSUER` | none — required outside `local` | Expected `iss` claim; also the JWKS base |
| `JIP_AUTH_AUTHORIZED_PARTIES` | none | Permitted `azp` values; comma-separated via the existing `CommaSeparated` helper |
| `JIP_AUTH_JWKS_URL` | `{issuer}/.well-known/jwks.json` | Override for testing or a pinned endpoint |
| `JIP_AUTH_JWKS_CACHE_SECONDS` | `3600` | JWKS cache lifetime |

These follow the Phase 0 convention: no defaults for values that must be
correct, so a misconfigured process fails at startup instead of running with
verification that silently accepts nothing — or worse, everything.

Real keys are never committed. `.env` is git-ignored; `.env.example` carries
placeholders only.

### Testing

Tests must not reach Clerk. The fixture generates an RSA keypair, serves a local
JWKS document, and mints tokens with it. The verification path under test stays
real — only the key source is local. Required cases: valid token resolves a
user; expired token, wrong `iss`, wrong `azp`, unknown `kid`, and `alg: none`
each produce 401.

## Consequences

**What this buys**

- No credential storage. No password hashing, reset flows, email verification,
  or MFA to build, maintain, or get wrong — and no credential breach surface in
  our database.
- Verification is stateless and offline. The API scales without a shared session
  store, and a slow Clerk API does not slow our request path.
- Vendor coupling is bounded to three places: one column in `users`, one
  verification module, and the provider component in the web app.

**What this costs**

- **A Clerk outage is an authentication outage.** Session tokens are short-lived
  by design, so there is no long-lived-token grace period to ride out a
  disruption — existing sessions stop being able to mint new tokens within about
  a minute. This is the real price of the choice. Acceptable for a personal
  tool; it would need discussion before this became something other people
  depend on.
- **Local development now requires network access to Clerk.** The Docker Compose
  stack was self-contained at the end of Phase 0 and no longer will be. This is
  a genuine regression in offline development and compounds DEV-003 in
  `known-issues.md`.
- User PII lives at Clerk, so data-subject requests are partly a vendor process.
- The free tier is bounded by monthly active users. Irrelevant for a personal
  tool; a cost input if scope changes.
- `middleware.ts` becomes `proxy.ts` on Next.js 16 — a rename to remember at
  upgrade time, and a silent failure mode if missed, since an unloaded
  middleware protects nothing.

## Alternatives considered

**Supabase Auth** — Real contender. Postgres-native, so the user table could
live in our own database and JWT verification is straightforward. Rejected
because its value is highest when Supabase also hosts the database, and this
project runs its own PostgreSQL with its own migrations; adopting only the auth
half means carrying the platform's conventions for a fraction of the benefit.
The natural choice if the database ever moves to Supabase.

**Auth0** — The most capable option and the most established. Rejected as
disproportionate: enterprise SSO, rules engines, and tenancy features that a
personal tool will not use, in exchange for a heavier configuration surface and
pricing that scales past the need.

**Self-hosted library (better-auth, Authlib)** — Full control, no vendor, no
outage dependency, and offline development preserved. Rejected on two grounds:
`docs/04-system-architecture.md` explicitly directs away from building
authentication, and it puts credential storage back in our database — the single
highest-consequence thing to get wrong, in a project whose stated priority is
trustworthiness.

**Building it directly** — Rejected by the architecture document, and correctly.

## To verify at implementation time

Confirmed against Clerk's documentation while writing this: RS256 signing, the
`{frontend-api}/.well-known/jwks.json` JWKS path, the required `exp` / `nbf` /
`azp` checks, the environment variable names, and the `middleware.ts` /
`proxy.ts` split at Next 16.

Not confirmed and to be checked against the current documentation before coding:

- The exact `iss` value for development and production instances (expected to be
  the Frontend API URL, e.g. `https://<slug>.clerk.accounts.dev` in development).
- The default session token lifetime. The design assumes it is short, on the
  order of a minute; the frontend's per-request `getToken()` rule depends on
  that being true, so confirm it rather than inherit the assumption.
- Whether the current `@clerk/nextjs` major version changes any helper names.
