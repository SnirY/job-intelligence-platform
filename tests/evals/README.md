# AI evaluation suite

Evaluation fixtures for the resume parser and the job parser.
`docs/09-mvp-roadmap.md` gates every AI feature on having one.

**Resumes** — `docs/11-engineering-standards.md` names the golden cases: Junior
Java Backend, Junior Python Backend, Computer Vision, Full Stack, and Ambiguous
Seniority. Each has a fixture in `fixtures/`, plus one case that exists purely
to prove the fabrication guard fires.

**Jobs** — five fixtures in `fixtures/jobs/`, covering requirement extraction,
importance classification, skill normalization, and role and seniority
analysis. Two of them exist to prove a guard fires rather than to measure
coverage: `promoted_preferences` marks every "Desirable" item as required, and
`fabricated_requirements` quotes three passages the posting never contained.

## Two modes, one set of expectations

Each fixture is a resume, a recorded model response, and a set of expectations.
The expectations are checked identically in both modes, which is the point —
the offline run is not a weaker approximation of the real one.

**Offline (default).** The recorded response is replayed through
`FakeLLMProvider`. This exercises everything the platform owns: prompt
rendering, structured parsing, schema validation, business validation, dates,
skill normalization, and the fabrication checks. It is deterministic, needs no
key, and runs in the normal suite.

```bash
pytest tests/evals
```

**Live.** The same resumes go to the configured provider and the same
expectations are applied to whatever comes back. This measures the model.
Skipped unless explicitly enabled, because `docs/11-engineering-standards.md`
forbids live model calls in the normal test run.

```bash
export JIP_RUN_AI_EVALS=1
export JIP_AI_API_KEY=...
pytest tests/evals -m live_ai
```

## The invariant that matters

```text
Hallucinated facts = 0
```

Everything else in a fixture is a coverage measure — did the parser find the
skills that are plainly written down. The fabrication checks are different in
kind: a fixture may under-extract and still be acceptable, but a candidate
carrying a number the resume never contained is a defect, and
`test_fabrication.py` fails on it.

## The job invariant

```text
Every requirement quotes the posting.
```

The resume equivalent of *hallucinated facts = 0*, and stricter in one way: a
resume candidate that fails the check is flagged for the user to judge, while a
job requirement that fails it is **dropped**. Nobody reviews job requirements
one by one, so a fabricated one would reach Phase 6's matcher unreviewed.

The second job guard is importance. `docs/05-ai-and-matching.md` requires that
"nice to have" never become "required", and the check reads the requirement's
own quoted text rather than trusting the classification: if the posting hedged,
the item is demoted whatever the model said. It only ever lowers an item —
promoting on a keyword is the error the guard exists to prevent.

## Adding a resume fixture

One JSON file in `fixtures/`:

| Key | Meaning |
|---|---|
| `name` | Human-readable case name |
| `resume_text` | The document as extracted text |
| `recorded_output` | A model response for the offline run |
| `expect_skills` | Canonical skill names that must be extracted |
| `expect_companies` | Employers that must be found |
| `expect_min_experiences` / `expect_min_projects` / `expect_min_education` | Floors, not exact counts — a parser finding *more* real detail is not a regression |
| `forbid_substrings` | Text that must not appear anywhere in the output. This is where a known hallucination goes once it has been seen |

## Adding a job fixture

One JSON file in `fixtures/jobs/`:

| Key | Meaning |
|---|---|
| `name` | Human-readable case name |
| `job_text` | The posting as stored text |
| `recorded_parse` / `recorded_analysis` | Two model responses for the offline run, in the order the pipeline calls them |
| `expect_requirements` | Normalized requirement text that must be extracted |
| `expect_min_requirements` / `expect_min_responsibilities` | Floors, not exact counts |
| `expect_max_requirements` | A ceiling, for a posting so thin that finding many requirements means inventing them |
| `expect_required` | Items that must keep their weight — the guard must not over-correct |
| `expect_preferred` | Items that must **not** arrive as required, and must not vanish either |
| `expect_requirement_types` | Types that must be present. Types drive weighting in Phase 6, so a work-authorization line filed as OTHER loses a blocker |
| `expect_skill_names` | Technologies that must be recorded, compared after canonical normalization |
| `expect_role_family` / `expect_seniority` | The correct judgements |
| `forbid_requirements` | Requirements that must not appear. Where a known invention goes once it has been seen |

## The tailoring invariant

```text
Invented metrics = 0
```

`docs/06-resume-engine.md` states it without qualification, and it is the only
rule in Phase 7 that a suggestion cannot be shown to have broken and still be
applied automatically. The check is deterministic
(`jip_api.application.resumes.truth`), so these evaluations run the *real*
validator over the recorded rewrite rather than asking a model whether its own
output was truthful.

A blocked suggestion is still shown to the user, with the figure quoted back —
they may know it is real, and the fix is then their profile rather than this one
document.

The second guard is the distinction between a **resume gap** (evidence you have
that this resume does not show, fixable by selecting differently) and a **career
gap** (evidence you genuinely lack, which no amount of rewriting fixes). A
career gap filed as a resume gap tells someone to rewrite their way out of
something they cannot.

**What these cannot catch**, per DEV-017: whether the API will compile the
response schema at all. Replaying a recorded response through a fake provider
proves the shape parses, not that Anthropic accepts it. Both tailoring schemas
were checked against the live API separately, and any change to them has to be
checked the same way.

## Adding a tailoring fixture

One JSON file in `fixtures/resumes/`:

| Key | Meaning |
|---|---|
| `name` | Human-readable case name |
| `job_text` / `match_summary` | What the strategy prompt is given |
| `selected` / `withheld` | The deterministic selection, and what was held back as unverified |
| `recorded_strategy` | A `resume_strategy_v1` response for the offline run |
| `expect_emphasize` | Terms the plan must lead with |
| `expect_career_gap_terms` | Terms that must appear under *career* gaps specifically |
| `forbid_strategy_terms` | Text that must not appear anywhere in the plan. Withheld evidence goes here: a plan that leads with an unconfirmed skill is recommending a claim the user never made |
| `items` | The resume lines, each with the career facts that support it |
| `recorded_rewrite` | A `resume_rewrite_v1` response for the offline run |
| `expect_all_safe` | True when nothing in the rewrite should need review |
| `expect_blocked_items` / `expect_blocked_numbers` | Exact sets, not floors — a *missed* fabrication and a *spurious* block are both defects |
| `expect_high_risk_items` | Items that must be marked for review |

Keep the resumes and postings fictional. These files are committed, and a real
resume would put someone's personal data in the repository.
