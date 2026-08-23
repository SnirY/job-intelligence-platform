# Board providers

One module per applicant-tracking system. Each reads one company's board and
returns `RawPosting`s.

| Provider | Endpoint | Notes |
|---|---|---|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `content=true` is required — without it there is no posting text. Sends HTML, entity-encoded. `location` is an object |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{name}` | Honour `isListed`: an unlisted posting is one nobody published |
| `lever` | `api.lever.co/v0/postings/{site}?mode=json` | Bare JSON array, not an object. `createdAt` is epoch **milliseconds**. Payload never names the company |

All three are public, unauthenticated and documented. Their response shapes were
confirmed against live responses on 2026-08-23; the fixtures in
`tests/test_providers.py` mirror what was seen.

## Adding one

1. A module here with a class exposing `name` and `fetch`, satisfying
   `base.JobSource`.
2. A line in `registry.PROVIDERS`.
3. Tests with a hand-written fixture, including a malformed row.

That is the whole ceremony. There is no plugin loader and there should not be
one at this size.

## The three rules

**The host is a constant in the module.** It never comes from configuration.
The only variable in a URL is the board token, and `BoardRef` validates that
before it can exist — which is what stops a token walking out of the path it
was given.

**A malformed row costs that row.** One bad posting in a hundred must not raise;
`_read` returns `None` and the other ninety-nine arrive.

**Nothing is inferred.** An absent location is `None`, never "Remote". An absent
date is `None`, never today. A field that cannot be read is missing, and missing
is a fact about the posting rather than a claim about the role.

## Deliberately absent

Auth-gated sources — LinkedIn, Indeed — are out of scope on terms-of-service
grounds and are not a matter of effort. Workday is out for a different reason:
its public surface varies per tenant, and one provider that works for a third of
tenants is worse than none.
