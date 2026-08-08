#!/usr/bin/env python
"""Run the same checks CI runs, in the same order.

    python scripts/run_checks.py              # everything except integration tests
    python scripts/run_checks.py --integration # include tests needing live services
    python scripts/run_checks.py --backend     # backend only

Every command is reported with its exit status, and the script keeps going after
a failure so one run surfaces every problem rather than only the first.

``--integration`` runs a five-second preflight first. Without it a stopped
Docker Desktop makes the suite hang silently instead of failing, which has cost
real time three separate times — and a service that is up but will not have you
turns every test that touches it red at once, which cost nine minutes once.
The preflight now answers both: it connects, and then it authenticates.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import urllib.parse
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


PREFLIGHT_TIMEOUT_SECONDS = 5.0
"""Long enough for a container that is up, far too short to look like work.

The whole point is that this either answers immediately or tells you the
service is gone. A generous timeout here would reintroduce exactly the wait it
exists to remove.
"""


def _handshake(url: str, scheme: str) -> str | None:
    """Complete the handshake the tests will need, not just the TCP connection.

    Imported inside the function so ``--frontend`` needs no backend driver.
    """
    try:
        if scheme.startswith("postgresql"):
            import psycopg

            # The URL carries SQLAlchemy's dialect suffix; libpq wants the bare
            # scheme. Everything after it — user, password, port, database — is
            # identical, which is the point of correcting only the prefix.
            dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
            with psycopg.connect(dsn, connect_timeout=int(PREFLIGHT_TIMEOUT_SECONDS)) as connection:
                connection.execute("SELECT 1")
        elif scheme.startswith("redis"):
            import redis

            redis.Redis.from_url(url, socket_timeout=PREFLIGHT_TIMEOUT_SECONDS).ping()
        else:
            # An unknown scheme is not a failure to report here. The socket
            # answered, and guessing at a handshake would invent a problem.
            return None
    except Exception as exc:
        # Deliberately broad. Every driver raises its own hierarchy, and the
        # whole purpose here is to turn any of them into one readable line
        # instead of a traceback from a script whose job is to report.
        return f"listening, but refused the connection — {exc}"

    return None


def _reachable(url: str) -> str | None:
    """Connect to whatever ``url`` points at and authenticate. Returns the failure.

    This was a bare socket connect until 2026-08-08, on the reasoning that it
    needed no driver, could not be confused by credentials, and answered the
    only question being asked: is anything listening?

    That was the wrong question. The preflight passed against a PostgreSQL that
    was listening and would not authenticate — the documented
    ``JIP_TEST_DATABASE_URL`` had no password in it — and the run it green-lit
    died 449 tests later on ``fe_sendauth: no password supplied``. Nine minutes,
    and a wall of red that reads as a catastrophic regression, to learn what one
    ``SELECT 1`` answers immediately.

    The socket connect stays as the first step. "Nothing is listening" and
    "listening and refusing you" are different problems with different fixes,
    and collapsing them into one message would trade this failure for a vaguer
    one.
    """
    parsed = urllib.parse.urlparse(url)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return f"could not read a host and port from {url!r}"

    try:
        with socket.create_connection((host, port), timeout=PREFLIGHT_TIMEOUT_SECONDS):
            pass
    except OSError as exc:
        return f"{host}:{port} — {exc.strerror or exc}"

    failure = _handshake(url, parsed.scheme)
    return None if failure is None else f"{host}:{port} — {failure}"


def preflight() -> bool:
    """Fail fast when the services the integration tests need are not there.

    Three times now a run has *hung* rather than failed because Docker Desktop
    had stopped: a connect that never answers reads as "slow" instead of "down",
    and pytest gives no output at all while it waits. The last one cost fifteen
    minutes of not knowing, and the answer was one `docker compose ps` away.

    So the wait is spent here instead, bounded to five seconds, with the layer
    below named in the failure. The tests themselves skip when these variables
    are unset, which is correct — but a variable that is set and pointing at
    nothing is a different situation, and the one that used to hang.
    """
    print("\n=== preflight: live services ===", flush=True)

    required = {
        "JIP_TEST_DATABASE_URL": os.environ.get("JIP_TEST_DATABASE_URL"),
        "JIP_TEST_REDIS_URL": os.environ.get("JIP_TEST_REDIS_URL"),
    }

    problems: list[str] = []
    for name, url in required.items():
        if not url:
            # Unset is the documented "I have no stack" case: pytest skips, and
            # that is a decision rather than a fault.
            print(f"  {name} is unset — those tests will skip", flush=True)
            continue

        failure = _reachable(url)
        if failure is None:
            print(f"  {name} reachable", flush=True)
        else:
            problems.append(f"{name}: {failure}")

    if not problems:
        return True

    print("\n--- preflight FAILED ---", flush=True)
    for problem in problems:
        print(f"  {problem}", flush=True)
    print(
        "\nThe run stops here. A service that is down makes the suite hang rather "
        "than fail;\na service that refuses the credentials makes every test that "
        "touches it red at once,\nwhich reads as a broken product. Neither is worth "
        "waiting through.\n\n"
        "If the stack should be up:\n"
        "  docker compose up -d postgres redis minio minio-init\n"
        "If it is up, check the URL against docs/development/local-environment.md "
        "— the\npassword and the port both come from .env, and 5432 is not the port.",
        flush=True,
    )
    return False


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

    # Before anything slow, and before anything that could hang.
    if run_backend and args.integration and not preflight():
        return 1

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
