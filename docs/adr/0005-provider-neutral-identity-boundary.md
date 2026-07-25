# ADR-0005 — Provider-neutral identity boundary

Status:
Accepted

Date:
2026-07-25

Relates to:
ADR-0004, which selects Clerk.

## Context

ADR-0004 chose Clerk and bounded the coupling to "one column, one verification
module, and the provider component in the web app". That was the intent; the
first implementation did not fully honour it. The column was named
`clerk_user_id`, the settings were `JIP_CLERK_*`, and the verifier class was
`ClerkTokenVerifier` — so the vendor's name was spread across the schema, the
configuration surface, and the type system.

None of that is expensive to change *now*: the `users` table is empty, the
migration has never run against a real database, and no product feature depends
on it yet. Every one of those facts stops being true the moment the first user
signs up. The cost of this decision is therefore near zero today and a data
migration with downtime later, which is the whole reason to take it before
merging rather than after.

The question this answers is not "will we leave Clerk" — that is unknown and
likely no. It is "if we ever want to, is that a configuration change or a
rewrite".

## Decision

Keep the vendor's name out of the schema, the configuration, and the
application layer. Confine it to the adapter and the frontend SDK, where it
genuinely belongs.

**Schema.** `users.clerk_user_id` becomes `users.external_user_id`, with a new
`users.auth_provider` column recording which issuer vouched for the row.
Uniqueness moves from `clerk_user_id` alone to
`(auth_provider, external_user_id)`.

Scoping uniqueness by provider is not cosmetic. Subject strings are only unique
*within* an issuer, so a bare unique constraint on the subject would let a
second provider's colliding `sub` hand one person's account to someone else. It
also means a migration can run with both issuers live, one user at a time,
rather than requiring a flag day.

**Configuration.** `JIP_CLERK_*` becomes `JIP_AUTH_*`. These were always OIDC
concepts — issuer, JWKS URL, authorized parties — not Clerk ones. A new
`JIP_AUTH_PROVIDER` (default `clerk`) supplies the value stored on new rows.

**Types.** A `TokenVerifier` Protocol with a single `verify` method, implemented
by `JwksTokenVerifier` — named for the mechanism, since RS256 plus a published
JWKS is what every OIDC issuer emits. `VerifiedIdentity` was already neutral and
is unchanged.

This restores consistency with Phase 0, where `TaskDispatcher` was a Protocol
from the start. Authentication was the outlier.

**Unchanged, because it was already right.** `users.id` remains an internal
UUID and is what every user-owned foreign key will reference. `provision_user`
already took a `VerifiedIdentity` rather than a Clerk object. Endpoints already
depend on `CurrentUser`, so every endpoint written from Phase 2 onward is
provider-neutral without anyone remembering to make it so.

**Not changed:** the frontend still uses `@clerk/nextjs` directly, and the
verifier still checks `azp` rather than `aud`.

## Consequences

- Moving to any OIDC issuer — Keycloak, Zitadel, Authentik, Logto, Auth0 —
  becomes configuration plus a small adapter change on the backend. The schema,
  the application layer, and every endpoint are untouched.
- Two providers can coexist in the table, so a migration is incremental rather
  than a cutover.
- `auth_provider` is a string rather than an enum. An enum would need a
  migration to add a value, which is precisely the friction this decision
  exists to avoid.
- The frontend remains the expensive half of any migration: `@clerk/nextjs`
  appears in the root layout, the middleware, both auth pages, `useApi`, the
  shell, and the landing page. This ADR does not address that, and abstracting
  a UI SDK behind an interface before there is a second implementation would be
  speculative.
- `azp` is checked instead of the standard `aud`, because that is what Clerk
  emits. An issuer using `aud` needs `verify_aud` enabled and an `audience`
  passed — a few lines in one method, flagged in `oidc.py`.
- The genuinely hard part of leaving a provider is untouched by any of this:
  password hashes, MFA enrolments, and OAuth links live at the provider.
  Whatever export path exists is a vendor question, and the always-available
  fallback is forcing a password reset for every user.

## Alternatives considered

**Leave the names as they were.** Honest about the current provider and zero
work. Rejected because the work is only cheap while the table is empty, and the
naming would have to be lived with or paid for later at a much worse moment.

**Abstract the frontend too, behind an internal auth interface.** Would make a
migration uniformly cheap. Rejected as premature: there is one implementation,
the shape a second one needs is unknown, and a wrong abstraction is harder to
remove than a direct dependency.

**Store profile data only, with no provider identifier.** Simpler schema, but
then a user can only ever be matched by email — which ADR-0004 already rejects
as an account-takeover path, and which the test suite asserts against.
