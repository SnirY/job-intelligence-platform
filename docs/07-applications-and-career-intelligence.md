# Application Tracker, Analytics & Career Intelligence

## Core principle

```text
Applications create outcomes.
Outcomes create data.
Data creates insights.
Insights improve future decisions.
```

## Application lifecycle

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

## Job vs Application

```text
Job = the opportunity
Application = the user's relationship with that opportunity
```

A job may exist without an application.

## Tracker views

MVP:

- Kanban
- table

Each application card can show:

- company
- role
- match
- current stage
- days in stage
- next action

## Timeline

Every meaningful change becomes an event.

Examples:

- application created
- status changed
- resume selected
- application submitted
- recruiter contacted
- interview scheduled
- interview completed
- rejection received
- offer received

History must never be overwritten.

## Applied state

When a user applies, preserve:

- applied date
- exact resume version
- application source
- optional notes

## Rejection

Store known feedback separately from system inference.

Do not state guessed rejection reasons as facts.

## Ghosted

The system may suggest marking an application as ghosted after a long period, but must not silently do so.

## Interview tracking

Future-ready interview types may include:

- recruiter
- HR
- technical
- live coding
- take-home
- system design
- hiring manager
- final

## Application analytics

Basic funnel:

```text
Jobs Saved
↓
Applications Submitted
↓
Responses
↓
HR Screens
↓
Technical Interviews
↓
Final Interviews
↓
Offers
```

Key metrics:

- apply rate
- response rate
- interview rate
- stage conversion
- time to response
- process duration

## Data thresholds

Do not produce strong conclusions from tiny samples.

Use explicit minimum-data thresholds.

## Career intelligence

Combine:

```text
Career Profile
+
Jobs
+
Matches
+
Applications
+
Resumes
+
Outcomes
```

to answer:

- Which roles fit best?
- Which roles actually respond?
- Which skills are most demanded?
- Which gaps appear in strongest opportunities?
- Which projects provide the most value?
- Where does the funnel break?
- What should the user do next?

## Observed job market

Unless the product has broad external market data, insights must refer to:

> Your observed job market

not “the entire market.”

## Relevant job set

Gap analysis should filter by:

- target roles
- location
- seniority
- user interest
- relevance

## Skill demand

For each skill, store:

- number of relevant jobs
- percentage
- core/required/preferred breakdown
- role distribution

## Gap states

```text
NO_GAP
WEAK_EVIDENCE
PARTIAL_GAP
STRONG_GAP
```

## Gap priority

Potential factors:

- demand frequency
- average importance
- opportunity quality
- current evidence
- learning difficulty
- portfolio demonstrability

## Opportunity-weighted demand

A gap appearing in high-fit jobs can be more important than one appearing in many low-fit jobs.

## Project intelligence

Prefer upgrading a strong existing project before recommending a generic new one.

Rank project opportunities by:

- number of gaps addressed
- demand of those gaps
- relevance to target roles
- project fit
- estimated effort

## Resume analytics

Track:

- applications per base resume
- responses
- interviews
- offers

Present as associations, not causal claims.

## Role-family analytics

For each role family:

- jobs saved
- average alignment
- applications
- response rate
- interview rate

## Insight types

```text
MARKET_INSIGHT
SKILL_GAP
ROLE_FIT
PROJECT_OPPORTUNITY
RESUME_SIGNAL
APPLICATION_SIGNAL
INTERVIEW_SIGNAL
NEXT_ACTION
```

Each insight should include:

- observation
- evidence
- confidence
- why it matters
- suggested action

## Recommendation engine

Types may include:

```text
APPLY_TO_JOB
PREPARE_APPLICATION
UPDATE_RESUME
FOLLOW_UP
LEARN_SKILL
UPGRADE_PROJECT
BUILD_PROJECT
UPDATE_PROFILE
PREPARE_INTERVIEW
```

Distinguish immediate actions from strategic actions.

## Next Best Action

The dashboard should show a small prioritized set, not dozens of recommendations.

## Initial learning approach

Use:

- descriptive analytics
- rule-based insights
- statistical signals

Do not train ML models on tiny personal datasets.

## Future Career Advisor Agent

The agent should consume reliable tools such as:

- get_current_pipeline
- get_top_opportunities
- get_skill_gaps
- get_resume_signals
- get_role_performance
- get_project_opportunities

Advice must be evidence-backed.
