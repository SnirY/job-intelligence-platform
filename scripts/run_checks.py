#!/usr/bin/env python
"""Run the same checks CI runs, in the same order.

    python scripts/run_checks.py              # everything except integration tests
    python scripts/run_checks.py --integration # include tests needing live services
    python scripts/run_checks.py --backend     # backend only

Every command is reported with its exit status, and the script keeps going after
a failure so one run surfaces every problem rather than only the first.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NPM = "npm.cmd" if os.name == "nt" else "npm"


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]


BACKEND_CHECKS = [
    Check("ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
    Check("ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    Check("mypy", [sys.executable, "-m", "mypy"]),
    Check("pytest (unit)", [sys.executable, "-m", "pytest", "-m", "not integration"]),
]

BACKEND_INTEGRATION_CHECKS = [
    Check("pytest (integration)", [sys.executable, "-m", "pytest", "-m", "integration"]),
]

FRONTEND_CHECKS = [
    Check("prettier", [NPM, "run", "format:check"]),
    Check("eslint", [NPM, "run", "lint"]),
    Check("tsc", [NPM, "run", "typecheck"]),
    Check("vitest", [NPM, "run", "test"]),
    Check("next build", [NPM, "run", "build"]),
]


def run(check: Check) -> bool:
    print(f"\n=== {check.name} ===", flush=True)
    result = subprocess.run(check.command, cwd=REPO_ROOT)
    if result.returncode != 0:
        print(f"--- {check.name} FAILED (exit {result.returncode}) ---", flush=True)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="store_true", help="run backend checks only")
    parser.add_argument("--frontend", action="store_true", help="run frontend checks only")
    parser.add_argument(
        "--integration",
        action="store_true",
        help="also run tests that need live PostgreSQL and Redis",
    )
    args = parser.parse_args()

    run_backend = args.backend or not args.frontend
    run_frontend = args.frontend or not args.backend

    checks: list[Check] = []
    if run_backend:
        checks += BACKEND_CHECKS
        if args.integration:
            checks += BACKEND_INTEGRATION_CHECKS
    if run_frontend:
        if shutil.which(NPM) is None:
            print(f"{NPM} not found on PATH; skipping frontend checks", file=sys.stderr)
        else:
            checks += FRONTEND_CHECKS

    failed = [check.name for check in checks if not run(check)]

    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
