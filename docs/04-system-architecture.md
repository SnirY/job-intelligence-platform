# System Architecture

## Architecture style

Use a **Modular Monolith**.

```text
One deployable backend
+
Strong internal module boundaries
```

Do not begin with microservices.

## High-level architecture

```text
Next.js Web
↓
FastAPI API
↓
Application Services
↓
Domain Modules
↓
PostgreSQL

Async Work
↓
Redis + RQ Worker

Files
↓
S3-compatible Object Storage

AI
↓
Provider Abstraction
```

## Monorepo

```text
job-intelligence-platform/

├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
├── packages/
│   ├── ai-core/
│   ├── shared-types/
│   ├── prompts/
│   └── config/
├── docs/
├── infra/
├── scripts/
├── tests/
└── docker-compose.yml
```

## Frontend

Recommended:

- Next.js
- TypeScript
- React
- Tailwind CSS
- shadcn/ui
- TanStack Query

Responsibilities:

- rendering
- forms
- interactions
- visualizations
- dashboard
- resume review
- application tracking

The frontend must not own:

- match scoring
- AI prompts
- resume truth validation
- domain rules

## Backend

Recommended:

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic

Layers:

```text
API
↓
Application
↓
Domain
↓
Infrastructure
```

## Domain modules

```text
users
career
jobs
matching
resumes
applications
insights
ai
```

Each module should preserve clear ownership.

## AI layer

The AI layer is an integration layer, not the domain.

Conceptual structure:

```text
AI Core
├── Providers
├── Model Router
├── Prompt Registry
├── Structured Outputs
├── Validation
└── Tracing
```

Important services:

- JobParsingService
- JobAnalysisService
- ResumeParsingService
- ResumeStrategyService
- SemanticMatchService

## Provider abstraction

Conceptual interface:

```text
LLMProvider
- generate_structured()
- generate_text()
- embed()
```

Adapters may include OpenAI, Anthropic, Gemini, or others.

Business logic must not depend on one provider.

## Background processing

Long-running operations should be async:

- job URL import
- job parsing
- job analysis
- match calculation
- resume parsing
- resume strategy generation
- rendering if expensive

Use a `TaskDispatcher` abstraction rather than calling RQ directly from application services.

## Database

Use PostgreSQL.

Use pgvector only when semantic retrieval adds real value.

## File storage

Do not store uploaded resume files in the relational database.

Use S3-compatible object storage behind an `ObjectStorage` interface.

## Authentication

Use a managed provider rather than building authentication from scratch.

The system must remain multi-user ready from day one.

## Async API pattern

```text
POST expensive operation
↓
202 Accepted
↓
processing_job_id
↓
Frontend polls status
↓
Fetch final resource when complete
```

MVP can use polling. The design should allow future SSE/WebSockets.

## Job ingestion pipeline

```text
Fetch raw content
↓
Extract main content
↓
Clean text
↓
Parse structured job
↓
Validate
↓
Analyze
↓
Match
```

URL fetching and semantic parsing must remain separate.

## Matching architecture

```text
Requirement Normalization
↓
Exact Skill Match
↓
Alias Match
↓
Evidence Match
↓
Semantic Match
↓
Rule-Based Score
↓
AI Explanation
```

The LLM does not decide the final score alone.

## Resume architecture

```text
Career Profile
+
Base Resume
+
Target Job
↓
Strategy
↓
Suggestions
↓
Truth Validation
↓
User Review
↓
Resume Version
```

## Security requirements

Implement:

- user data isolation
- signed file URLs
- input validation
- rate limiting on expensive operations
- secret management
- SSRF protection for job URL imports
- no API keys in the frontend

## Local development

Docker Compose should run:

- web
- api
- worker
- PostgreSQL
- Redis

## Deployment direction

Possible MVP deployment:

- Frontend: Vercel
- API/Worker: Railway, Render, or Fly.io
- PostgreSQL: Neon or Supabase
- Redis: Upstash
- Storage: Cloudflare R2 or S3-compatible service

## Architecture rules

- no direct AI-to-database trusted writes
- business logic outside controllers
- queue long operations
- preserve raw inputs
- provider independence
- strong feature boundaries
- agents access application tools, not the database directly

## Development philosophy

Build vertical slices.

Example:

```text
Add Job
→ persist
→ API
→ UI
→ tests
```

Then:

```text
Analyze Job
→ persist
→ API
→ UI
→ tests
```
