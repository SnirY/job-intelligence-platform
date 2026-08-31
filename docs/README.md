# Documentation

Twelve specification documents, written before the code and maintained
alongside it. They are numbered in reading order: 00 explains what the product
is for, and each one after it narrows.

| | |
|---|---|
| [`00-product-vision.md`](00-product-vision.md) | Vision, and what this is not |
| [`01-product-requirements.md`](01-product-requirements.md) | Scope, and what the MVP excludes |
| [`02-user-flows.md`](02-user-flows.md) | The journeys, end to end |
| [`03-domain-model.md`](03-domain-model.md) | Entities, and the rules their data must keep |
| [`04-system-architecture.md`](04-system-architecture.md) | Layers, boundaries, and the async pattern |
| [`05-ai-and-matching.md`](05-ai-and-matching.md) | Where AI is allowed to decide, and where it is not |
| [`06-resume-engine.md`](06-resume-engine.md) | Career truth, tailoring, and the fabrication rules |
| [`07-applications-and-career-intelligence.md`](07-applications-and-career-intelligence.md) | The tracker, and what the history is for |
| [`08-ui-ux.md`](08-ui-ux.md) | UI direction and the language of the screens |
| [`09-mvp-roadmap.md`](09-mvp-roadmap.md) | The build order, and why that order |
| [`10-api-contracts.md`](10-api-contracts.md) | Request and response shapes |
| [`11-engineering-standards.md`](11-engineering-standards.md) | Coding, testing, and review rules |
| [`12-project-tracking.md`](12-project-tracking.md) | How continuity is kept between sessions |

## Decisions

[`adr/`](adr) — seven architecture decisions, each recording the alternative
that was rejected and why. A decision argued once and never written down gets
re-argued.

## Development

The tracking files, which describe what is true rather than what was planned:

| | |
|---|---|
| [`development/implementation-status.md`](development/implementation-status.md) | What exists, and where it is thinner than it looks |
| [`development/known-issues.md`](development/known-issues.md) | Every defect found, its cause, and what was done |
| [`development/dev-011-results.md`](development/dev-011-results.md) | The matching engine calibrated against real postings, by hand |
| [`development/manual-verification-checklist.md`](development/manual-verification-checklist.md) | What a person walked, on what date, and what it found |
| [`development/ui-invariants.md`](development/ui-invariants.md) | The rules a screen keeps no matter how it looks |
| [`development/screen-inventory.md`](development/screen-inventory.md) | Every screen, and what it is responsible for |
