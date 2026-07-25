# Packages

Shared code used by more than one application.

| Package | Language | Status | Purpose |
|---|---|---|---|
| `config/` | Python (`jip-config`) | Implemented | Settings and structured logging shared by the API and worker |
| `shared-types/` | TypeScript (`@jip/shared-types`) | Implemented | Response envelope and API contracts shared by the web app |
| `ai-core/` | Python | Not started | Provider abstraction, model router, structured outputs, tracing |
| `prompts/` | — | Not started | Versioned prompt registry |

`ai-core/` and `prompts/` are named in `docs/04-system-architecture.md` and are
intentionally absent from the tree until Phase 5, when the first AI feature is
built. An empty package with no behaviour would be scaffolding that has to be
redesigned once the real requirements exist.
