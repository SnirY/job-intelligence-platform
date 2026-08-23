# Scripts

Developer and CI helper scripts.

## `run_checks.py`

Runs the same checks as the CI workflow, in the same order.

```bash
python scripts/run_checks.py                # everything except integration tests
python scripts/run_checks.py --integration  # include tests needing live services
python scripts/run_checks.py --backend      # backend only
python scripts/run_checks.py --frontend     # frontend only
```

Requires the backend virtual environment to be active (see the repository
README) and `npm install` to have been run for the frontend checks.

## `seed_dev_data.py`

Fills a development account with enough data to look at the screens.

```bash
python scripts/seed_dev_data.py
```

Four screens shipped in Phase 12 and none of them shows anything on an empty
account. Reaching them by hand means building a profile, saving a job, running
an analysis, running a match, adding a board and scanning it — twenty minutes of
clicking before twenty minutes of looking, which is how a manual walkthrough
stops happening. Stage 2.13 of `manual-verification-checklist.md` is what this
exists to make walkable.

**No model is called and nothing costs money.** The analysis and its
requirements are written directly, and `run_match` is deterministic — it takes a
profile snapshot and a list of requirements and needs no provider at all.

It makes one clean job, one job that trips every legitimacy rule, one job with a
real link, a genuine match, a watched board, and two candidates already in the
review list. Everything is tagged `[seed]` and a second run reports what is
already there rather than making a second copy.

It picks the account you signed in with most recently and says which one, since
signing in twice is normal here. Pass `--user` with any part of a Clerk id to
choose another; with no match it prints the list. It matches on
`external_user_id` rather than email, because `users.email` is null in an
ordinary local setup — `provisioning._sync_profile` explains why: Clerk's
default session token carries no email claim.

**It refuses to run against anything but a local database**, and checks that
twice: the environment setting is the stated intent and the database host is the
fact. Either one alone is a check somebody can be wrong about — a `.env` copied
from staging says local, and a local `.env` can point at a remote database.

It never creates a user. A user row is minted by signing in, and a script that
invented one would produce an account nobody can log into, which looks like
seeding worked and is worse than failing.
