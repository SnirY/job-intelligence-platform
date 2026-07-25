"""Job Intelligence Platform HTTP API.

Layering (see ``docs/11-engineering-standards.md``)::

    api            HTTP surface: validation, use-case invocation, response mapping
    core           cross-cutting concerns: errors, response envelopes, logging
    infrastructure adapters: database sessions, task queue

``application/`` and ``domain/`` packages are intentionally absent until the
first domain module is implemented; empty layers would be scaffolding without
behaviour.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("jip-api")
except PackageNotFoundError:  # pragma: no cover - only hit in a non-installed tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
