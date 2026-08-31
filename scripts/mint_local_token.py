"""Print a bearer token the API will accept when JIP_AUTH_PROVIDER=local.

    python scripts/mint_local_token.py
    python scripts/mint_local_token.py --subject demo-2 --ttl 3600

The token goes in an `Authorization: Bearer <token>` header. Nothing is written
anywhere: the user row is provisioned by the API on first sight of the subject,
the same way it is for a real issuer.

Refuses to run outside a local or test environment, matching the verifier it
mints for. A token this script produces is worthless to a correctly configured
staging or production API, which will not have built the local verifier at all.
"""

from __future__ import annotations

import argparse
import sys

from jip_api.infrastructure.auth.local import DEFAULT_SUBJECT, mint_local_token
from jip_config import Environment, get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", default=DEFAULT_SUBJECT, help="`sub` claim to mint for.")
    parser.add_argument("--email", default=None)
    parser.add_argument("--name", default=None, dest="display_name")
    parser.add_argument("--ttl", type=int, default=86_400, help="Seconds until it expires.")
    args = parser.parse_args()

    settings = get_settings()

    if settings.environment not in (Environment.LOCAL, Environment.TEST):
        print(
            f"Refusing to mint: JIP_ENVIRONMENT is {settings.environment.value}. "
            "Local tokens are for local and test only.",
            file=sys.stderr,
        )
        return 1

    if not settings.uses_local_auth:
        print(
            f"JIP_AUTH_PROVIDER is {settings.auth_provider!r}, not 'local'. "
            "The API would verify against a JWKS and reject this token.",
            file=sys.stderr,
        )
        return 1

    if not settings.auth_local_secret:
        print("JIP_AUTH_LOCAL_SECRET is not set.", file=sys.stderr)
        return 1

    try:
        token = mint_local_token(
            settings.auth_local_secret,
            subject=args.subject,
            email=args.email,
            display_name=args.display_name,
            ttl_seconds=args.ttl,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
