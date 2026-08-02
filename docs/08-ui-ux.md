# UI/UX Specification & Screen Architecture

## Experience vision

The product should feel:

```text
Professional
Intelligent
Modern
Positive
Calm
Motivating
Data-Rich
Action-Oriented
```

It should feel like:

```text
Career Command Center
+
Personal Intelligence Dashboard
+
Application Workspace
+
Career Progress System
```

not a spreadsheet, ATS, generic CRM, or generic AI chatbot.

## Core UX principle

Every important screen should answer:

1. What am I looking at?
2. Why does it matter?
3. What should I do next?

## Emotional direction

Job searching can feel uncertain and discouraging.

The product should create:

- clarity
- control
- progress
- evidence
- small wins

Use positive framing without hiding bad news.

## Visual philosophy

Use:

- generous whitespace
- strong typography
- subtle depth
- restrained gradients
- smooth motion
- clear grouping
- advanced but useful visualizations

Avoid:

- dense enterprise layouts
- excessive borders
- too many colors
- tiny text
- constant modals
- aggressive warning language

## Color semantics

Suggested semantic roles:

- strong match → green
- opportunity/action → blue
- transferable match → purple
- improvement gap → amber
- blocker/error → red

Never rely on color alone.

## Light and dark mode

Design for both from the beginning.

## Main navigation

```text
Home
Jobs
Applications
Resumes
Career Profile
Insights
Settings
```

Global primary action:

```text
+ Add Job
```

## Dashboard

Recommended sections:

- current state
- next best actions
- pipeline
- top opportunities
- career momentum
- skill intelligence
- recent activity

The dashboard should be opinionated and prioritize what matters now.

## Next Best Actions

Show at most 3–5 prioritized actions.

Example:

```text
Apply to Junior Backend Engineer
Finish resume for Company B
Prepare for tomorrow's technical interview
```

## Job list

Support:

- smart list
- table
- cards

Useful filters:

- role family
- match range
- recommendation
- company
- location
- work mode
- seniority
- application status
- date added

Smart presets:

- Strong Opportunities
- Ready to Apply
- High Match With Small Gaps
- Recently Added
- Stretch Opportunities

## Job detail

Suggested structure:

- job header
- opportunity overview
- match map
- requirements
- evidence
- resume strategy
- career impact
- application timeline

## Match visualization

Use more than one number.

Possible components:

- alignment ring
- horizontal category bars
- requirement coverage
- radar chart as supplemental visualization
- requirement-level match cards

## Evidence drawer

Users should be able to ask:

> Why does the system think I match this?

and see the exact evidence.

## Career impact section

A job can teach the system even if the user never applies.

Show recurring gaps revealed by the opportunity.

## Application preparation workspace

Suggested desktop layout:

```text
Job Requirements | Resume Workspace | Coverage / Strategy
```

## Resume Studio

Show:

- real page preview
- suggestion panel
- job requirement coverage
- truth indicators
- diff-based changes

Suggestion actions:

- Accept
- Reject
- Edit
- Alternative

## Career gap vs resume gap

Present these visually as different concepts.

### Resume gap

Evidence exists, but it is not visible.

### Career gap

No verified evidence currently exists.

## Application tracker

Default to a polished visual Kanban.

Cards can show:

- role
- company
- match
- days in stage
- next action

Use subtle stage-aging indicators.

## Insights

The Insights page should feel like a Narrative Intelligence Dashboard, not a wall of charts.

Recommended sections:

- career direction
- skill demand
- opportunity landscape
- application performance
- project opportunities
- progress

## Settings

Career preferences, and nothing that belongs to another screen. Account
identity and sign-out stay with the avatar menu, where Clerk owns them.

Sections:

- work mode and employment type
- locations, and whether relocation is open
- salary expectations
- excluded role types

Every field is optional and blank must read as *no constraint*, never as a
constraint of zero — the same rule the match panel applies to an absent score.

The screen states what reads each preference. A user who sets "remote only" and
then sees an on-site job recommended has been told something untrue by
omission, and the fix is not to hide the recommendation but to say which
preferences it accounted for. Nothing here filters silently.

## Signature visualizations

### Career Opportunity Map

Map role families using:

- alignment
- strategic value
- opportunity count
- momentum

### Career Gap Impact Map

Plot gaps by:

- demand/impact
- estimated effort

### Career Evidence Map

Visualize how skills connect to projects and experiences.

## Visualization principle

Every chart must answer a question.

Charts should support:

- hover details
- click-to-filter
- drill-down
- accessible text summaries

## Positive language

Prefer:

```text
7 areas could strengthen your match.
```

over:

```text
Missing Skills: 7
```

But do not soften true blockers until they become unclear.

## Loading states

For AI pipelines, use named progress steps rather than a generic spinner.

Example:

```text
Extracting content
Identifying requirements
Finding relevant evidence
Building your match profile
```

## Empty states

Use action-oriented copy.

Example:

> Add your first job to start building your career intelligence.

## Motion

Use subtle, functional animation only.

Examples:

- panels sliding in
- charts animating once
- kanban cards moving naturally
- numbers transitioning

Avoid decorative constant motion.

## Accessibility

Support:

- keyboard navigation
- visible focus
- screen readers
- color contrast
- reduced motion
- textual alternatives for charts

## Mobile

Core read/update flows should work on mobile.

Resume Studio and advanced analytics may remain desktop-first.

## MVP screens

- Authentication
- Onboarding
- Dashboard
- Jobs
- Add Job
- Job Detail
- Application Preparation
- Resume Strategy
- Resume Studio
- Resumes
- Applications Kanban
- Application Detail
- Career Profile
- Insights
- Settings

## UX success criteria

The UI succeeds when:

- the next action is always clear
- complex analysis feels understandable
- positivity does not hide problems
- visualizations reveal useful insight
- AI recommendations are visibly distinct from facts
- progress feels visible
- the product feels personal, not generic
