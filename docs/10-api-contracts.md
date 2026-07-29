# API Contracts & Technical Interfaces

## API principles

Use:

- REST
- `/api/v1`
- resource-oriented endpoints
- typed request/response models
- consistent errors
- async processing for long operations

## Standard success response

```json
{
  "data": {}
}
```

Collections:

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 0,
    "total_pages": 0
  }
}
```

## Standard error response

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "The requested job could not be found.",
    "details": null,
    "request_id": "..."
  }
}
```

Use machine-readable error codes.

## HTTP status conventions

- 200 read/update success
- 201 created
- 202 async accepted
- 204 no content
- 400 malformed request
- 401 unauthenticated
- 403 forbidden
- 404 not found
- 409 conflict
- 422 validation
- 429 rate limit
- 500 unexpected failure

## IDs

Use UUID or UUIDv7.

## Time

Use ISO 8601 UTC in the API.

## Authentication

Backend resolves the authenticated user.

Never accept a client-provided `user_id` as authorization.

## Pagination

```text
?page=1&page_size=20
```

Default 20, maximum 100.

## Career API

```text
GET    /api/v1/career/profile
PATCH  /api/v1/career/profile

GET    /api/v1/career/target-roles
POST   /api/v1/career/target-roles
PATCH  /api/v1/career/target-roles/{id}
DELETE /api/v1/career/target-roles/{id}

GET    /api/v1/career/skills
POST   /api/v1/career/skills
PATCH  /api/v1/career/skills/{id}
DELETE /api/v1/career/skills/{id}

GET    /api/v1/career/projects
POST   /api/v1/career/projects
GET    /api/v1/career/projects/{id}
PATCH  /api/v1/career/projects/{id}
DELETE /api/v1/career/projects/{id}

GET    /api/v1/career/experiences
POST   /api/v1/career/experiences

GET    /api/v1/career/education
POST   /api/v1/career/education
```

## Resume import

```text
POST /api/v1/resumes/import
```

Returns `202 Accepted` with:

- source_document_id
- processing_job_id
- status

Review:

```text
GET /api/v1/resumes/imports/{source_document_id}/extraction
```

Confirm:

```text
POST /api/v1/resumes/imports/{source_document_id}/confirm
```

AI extraction must not write verified profile data directly.

## Jobs API

```text
POST /api/v1/jobs
GET  /api/v1/jobs
GET  /api/v1/jobs/{id}

GET  /api/v1/jobs/{id}/source

GET  /api/v1/jobs/{id}/analysis
POST /api/v1/jobs/{id}/analysis

GET  /api/v1/jobs/{id}/requirements

GET  /api/v1/jobs/{id}/match
POST /api/v1/jobs/{id}/match

GET  /api/v1/jobs/{id}/match/items
```

Create jobs using one endpoint with `import_method`:

```text
PASTED_DESCRIPTION
URL
MANUAL
```

Possible duplicate returns 409 with the existing job ID and match reason.

## Match summary

Should include:

- overall score
- alignment label
- recommendation
- confidence
- summary
- category scores
- counts by match status

## Match items

Each item includes:

- exact requirement
- match status
- score
- weight
- confidence
- explanation
- evidence references

## Resumes API

```text
GET  /api/v1/resumes
POST /api/v1/resumes
GET  /api/v1/resumes/{resume_id}

GET  /api/v1/resumes/{resume_id}/versions
POST /api/v1/resumes/{resume_id}/versions

GET  /api/v1/resume-versions/{version_id}
PUT  /api/v1/resume-versions/{version_id}/content
POST /api/v1/resume-versions/{version_id}/status

GET  /api/v1/jobs/{job_id}/resume-strategies
POST /api/v1/jobs/{job_id}/resume-strategies
POST /api/v1/resume-strategies/{strategy_id}/suggestions

POST /api/v1/resume-suggestions/{id}/accept
POST /api/v1/resume-suggestions/{id}/reject
POST /api/v1/resume-suggestions/{id}/edit

POST /api/v1/resume-strategies/{strategy_id}/finalize

GET  /api/v1/resume-versions/{version_id}/render
```

Used resume versions must be immutable. `PUT .../content` and
`POST .../status` are refused with 409 once a version reaches USED or ARCHIVED.

Two deviations from the first draft of this list, both made while building
Phase 7:

- **Render is `GET`, not `POST`.** It has no side effects and returns a
  representation of an existing resource, so `POST` would have misdescribed it
  and made the result unlinkable. The response is `text/html` with
  `Content-Disposition: inline` — see ADR-0006.
- **`GET /jobs/{job_id}/resume-strategies` was added.** It returns the newest
  strategy with its suggestions, or a null one carrying `can_create` and
  `blocking_reason`, matching how `GET /jobs/{id}/match` reports `can_match`.
  Without it the UI would have to guess whether the `POST` would succeed.

## Applications API

```text
POST  /api/v1/applications
GET   /api/v1/applications
GET   /api/v1/applications/{id}

PATCH /api/v1/applications/{id}/status

GET   /api/v1/applications/{id}/events
POST  /api/v1/applications/{id}/notes
```

Every status change must:

1. validate the transition
2. update current status
3. create an event

preferably in one transaction.

## Dashboard API

Use an aggregate endpoint:

```text
GET /api/v1/dashboard
```

The endpoint aggregates existing domain outputs. It must not duplicate business logic.

## Insights API

```text
GET /api/v1/insights/overview
GET /api/v1/insights/skills/demand
GET /api/v1/insights/skills/gaps
GET /api/v1/insights/roles
GET /api/v1/insights/applications/funnel
```

## Processing Jobs API

```text
GET  /api/v1/processing-jobs/{id}
POST /api/v1/processing-jobs/{id}/retry
```

Statuses:

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

Example job-processing progress steps:

```text
FETCHING
EXTRACTING
PARSING
ANALYZING
MATCHING
COMPLETED
```

## Polling

MVP can poll every 2–5 seconds until terminal state.

The architecture should allow later SSE/WebSockets.

## Internal interfaces

### JobFetcher

```text
fetch(url) -> FetchResult
```

### ContentExtractor

```text
extract(raw_content) -> ExtractedContent
```

### JobParser

```text
parse(job_content) -> JobParseResult
```

### JobAnalyzer

```text
analyze(parsed_job) -> JobAnalysisResult
```

### MatchEngine

```text
match(job_requirements, career_evidence) -> MatchResult
```

Must be testable without HTTP.

### SemanticMatchService

```text
analyze_transferability(requirement, relevant_evidence)
```

Final classification still passes through domain rules.

### ScoreCalculator

```text
calculate(match_items) -> MatchScoreResult
```

Must be deterministic.

### RecommendationEngine

```text
recommend(match_result, job, career_preferences)
```

Mostly rule-driven.

### ResumeParsingService

```text
parse(document) -> ResumeExtractionDraft
```

### ResumeStrategyService

```text
generate_strategy(job, match_result, career_profile, base_resume)
```

### ResumeTruthValidator

```text
validate(statement, source_context) -> TruthValidationResult
```

### ResumeRenderer

```text
render(structured_resume, template, format)
```

### TaskDispatcher

Application code calls a generic dispatcher rather than RQ directly.

### ObjectStorage

Provide:

- upload
- download
- delete
- create_signed_url

### LLMProvider

Provide:

- generate_structured
- generate_text
- generate_embedding

### AIModelRouter

Route operations such as:

```text
JOB_PARSE
JOB_ANALYSIS
SEMANTIC_MATCH
RESUME_PARSE
RESUME_STRATEGY
RESUME_REWRITE
```

## Prompt registry

Use a central versioned prompt registry.

## AI failures

Classify:

```text
PROVIDER_ERROR
RATE_LIMIT
TIMEOUT
INVALID_OUTPUT
VALIDATION_FAILURE
CONTENT_UNAVAILABLE
```

## Idempotency

Use input hashes and operation versions for expensive repeatable operations.

## Domain events

Useful internal events may include:

- CareerProfileUpdated
- JobAnalysisCompleted
- JobMatchCompleted
- ResumeVersionCreated
- ApplicationStatusChanged

No Kafka is required.

## Freshness

Matches should preserve:

- career profile version
- job analysis version
- matching engine version

If inputs change, mark results stale.

The same applies to resume strategies.

## Security contracts

All user-owned queries must enforce ownership.

URL import must protect against SSRF.

Uploads must validate size, MIME type, extension, and content handling.

Do not expose stack traces, provider keys, or internal prompts to the frontend.

## OpenAPI

Use typed Pydantic request and response models so FastAPI OpenAPI can serve as the generated client contract.
