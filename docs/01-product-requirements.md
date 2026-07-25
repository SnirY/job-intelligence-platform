# Product Requirements

## Product objectives

The platform should help users:

- **Find** — collect jobs from different sources
- **Understand** — turn job descriptions into structured intelligence
- **Match** — compare opportunities against a persistent career profile
- **Improve** — identify real skill, evidence, and portfolio gaps
- **Apply** — create truthful job-specific resumes
- **Track** — manage the application lifecycle
- **Learn** — use accumulated outcomes to improve future decisions

## Core product modules

### Career Profile

The professional source of truth.

Includes:

- personal information
- target roles
- career preferences
- skills
- experience
- education
- projects
- certifications
- achievements
- evidence
- reusable verified statements

### Job Ingestion

MVP:

- paste job URL
- paste job description
- manual entry

Future:

- browser extension
- mobile share
- email import
- automatic discovery
- job-board integrations

### Job Intelligence

Extract and analyze:

- title
- company
- location
- work mode
- employment type
- role family
- seniority
- responsibilities
- required skills
- preferred skills
- experience expectations
- education requirements

### Matching Engine

Return:

- overall alignment
- category scores
- strong matches
- partial matches
- transferable matches
- gaps
- blockers
- evidence
- application recommendation

### Resume Intelligence

Support:

- master resume
- base resumes
- job-specific versions
- strategy generation
- project prioritization
- skill prioritization
- bullet rewrites
- truth validation
- user review
- export

### Gap Intelligence

Analyze both:

- job-specific gaps
- cross-job recurring gaps

Distinguish:

- career gap
- resume gap
- weak evidence

### Project Intelligence

Recommend:

- upgrade an existing project first where possible
- build a new project only when needed
- prioritize projects by career ROI

### Application Tracker

Stages:

```text
SAVED
INTERESTED
ANALYZING
PREPARING
READY_TO_APPLY
APPLIED
HR_SCREEN
TECHNICAL_INTERVIEW
FINAL_INTERVIEW
OFFER
REJECTED
WITHDRAWN
GHOSTED
ARCHIVED
```

### Career Analytics

Eventually include:

- funnel
- interview rate
- response rate
- role-family performance
- skill demand
- recurring gaps
- resume-associated outcome signals

## MVP scope

The MVP must support:

1. Create a career profile.
2. Upload and parse a resume.
3. Review extracted profile data.
4. Add a job.
5. Parse and analyze the job.
6. Produce an evidence-backed match report.
7. Recommend whether to apply.
8. Create a truthful tailored resume.
9. Export the resume.
10. Track the application.
11. Show basic aggregated insights.

## Product rules

### Never fabricate

Never add unsupported skills, experience, metrics, responsibilities, achievements, technologies, users, revenue, or scale.

### User approval

Meaningful changes to verified profile facts and resume content require user review or confirmation.

### Explain recommendations

Never present only a number. Show why.

### Separate facts from analysis

Example:

**Fact:** The job requests 2 years of experience.

**Analysis:** The role otherwise appears junior-oriented and the requirement may be flexible.

### Preserve source data

Keep original job descriptions and original uploaded resumes.

### Recommendations need evidence

Do not say only “Learn Docker.” Explain why it matters.

## Explicit MVP exclusions

Do not include initially:

- automatic job application
- mass application
- full LinkedIn scraping
- automatic recruiter messaging
- complex multi-agent orchestration
- interview simulator
- native mobile application
- large-scale ML ranking
- cross-user benchmarking
