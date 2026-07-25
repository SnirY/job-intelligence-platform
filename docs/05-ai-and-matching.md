# AI Architecture & Matching Engine

## Core principle

```text
AI interprets.
The system decides.
Evidence explains.
```

## AI responsibilities

AI may handle:

- job-description understanding
- structured requirement extraction
- classification
- seniority interpretation
- semantic reasoning
- transferable-skill reasoning
- resume parsing
- resume strategy
- explanation generation

AI must not independently control:

- verified career facts
- final deterministic scoring
- application status
- permissions
- trusted database state

## General AI pipeline

```text
Input
↓
Input Validation
↓
Context Preparation
↓
Prompt Construction
↓
Model Call
↓
Structured Output
↓
Schema Validation
↓
Business Validation
↓
Persistence
```

## Structured outputs

Important operations require typed outputs such as:

- JobParseResult
- JobAnalysisResult
- SemanticMatchResult
- ResumeParseResult
- ResumeStrategyResult

All structured outputs must pass schema validation.

## Requirement extraction

A long sentence should be decomposed into separate requirements when appropriate.

Example:

```text
2+ years of backend experience using Java, Spring Boot or similar technologies
```

may become:

- experience requirement
- Java requirement
- Spring Boot or similar framework requirement

Always preserve original text.

## Requirement importance

Classify into:

```text
CORE
REQUIRED
PREFERRED
OPTIONAL
UNKNOWN
```

Importance must preserve source meaning. “Nice to have” must not become “required.”

## Skill normalization

Use:

```text
Raw Skill
↓
Alias Lookup
↓
Canonical Skill
```

AI may suggest normalization only when a skill is unknown.

## Role classification

Initial role families may include:

- Backend Engineering
- Frontend Engineering
- Full Stack Engineering
- Software Engineering
- AI / ML
- Data Engineering
- Computer Vision
- DevOps
- Cybersecurity

Support primary and secondary classifications where useful.

## Seniority analysis

Use signals from:

- title
- years requested
- responsibility scope
- architecture ownership
- leadership
- mentoring

Possible levels:

```text
INTERN
ENTRY_LEVEL
JUNIOR
MID
SENIOR
STAFF_PLUS
UNKNOWN
```

## Evidence-first matching

For each requirement:

```text
Exact Match
↓
Alias Match
↓
Evidence Retrieval
↓
Semantic Match
↓
Transferability Analysis
↓
Match Classification
↓
Score
↓
Explanation
```

## Match statuses

```text
STRONG_MATCH
MATCH
PARTIAL_MATCH
TRANSFERABLE_MATCH
GAP
BLOCKER
UNKNOWN
```

Semantic similarity must not be treated as equivalence.

Example:

```text
Django ≠ Spring Boot
```

but Django experience may support a transferable backend-framework match.

## Requirement score

A starting mapping may be:

```text
STRONG_MATCH        100
MATCH                85
PARTIAL_MATCH        60
TRANSFERABLE_MATCH   50
UNKNOWN              35
GAP                   0
BLOCKER               0
```

Exact values must be versioned and calibrated.

## Weighted score

```text
Weighted Match =
Σ(requirement_score × requirement_weight)
/
Σ(requirement_weight)
```

Category scores should be preserved separately.

Possible categories:

- technical
- experience
- projects
- education
- domain
- preferred requirements

## Blockers and score caps

Real blockers may cap the overall score.

Examples:

- required work authorization
- mandatory security clearance
- required professional license
- missing absolutely core technology

## Years of experience

Do not treat years as binary.

Strong relevant project evidence and transferable experience may produce a partial match.

## Project evidence

Rank projects by:

- skill overlap
- role relevance
- capability overlap
- recency
- depth

## Recommendation engine

Possible outputs:

```text
STRONG_APPLY
APPLY
CONSIDER
LOW_PRIORITY
PROBABLY_SKIP
```

Recommendations consider more than the overall score:

- blockers
- core requirements
- role alignment
- seniority
- location
- user preferences
- gap severity

## Explainability

Every important match should expose:

```text
Requirement
↓
Classification
↓
Evidence
↓
Score
↓
Explanation
```

## Confidence

Low-confidence AI interpretation should become `UNKNOWN` or require review rather than a confident guess.

## Resume truth validation

Every generated statement should be decomposed into claims and checked against verified evidence.

Statuses:

```text
SAFE
REQUIRES_CONFIRMATION
UNSUPPORTED
BLOCKED
```

## Prompt architecture

Prompts must be centrally managed and versioned.

Examples:

```text
job_parser_v1
job_analysis_v1
seniority_analysis_v1
semantic_match_v1
resume_parser_v1
resume_strategy_v1
resume_rewrite_v1
```

## Model routing

Use stronger models only where necessary.

Possible routing:

- extraction/classification → fast model
- complex reasoning → stronger model
- semantic retrieval → embeddings

The routing must be configuration-driven.

## Evaluation

Create evaluation fixtures for:

- job parsing
- requirement extraction
- importance classification
- skill normalization
- false strong matches
- false blockers
- transferable evidence
- resume hallucinations

The strongest resume invariant:

```text
Hallucinated facts = 0
```

## Score meaning

Never present:

```text
82% chance of getting hired
```

Present:

```text
82% profile-to-job alignment
```

## Agents

Agents sit above reliable application services.

Example future Career Advisor tools:

- get_career_profile
- get_top_jobs
- get_job_match
- get_skill_gaps
- get_application_stats
- get_project_portfolio
- create_recommendation

Agents do not directly access the database.
