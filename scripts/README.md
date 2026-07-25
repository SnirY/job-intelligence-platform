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
