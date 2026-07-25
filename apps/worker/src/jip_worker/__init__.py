"""Job Intelligence Platform background worker.

Tasks are executed by RQ. The API enqueues them by dotted import path
(``jip_worker.tasks.system.ping``), so this package is never imported by the API
process and the dependency direction stays one-way.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("jip-worker")
except PackageNotFoundError:  # pragma: no cover - only hit in a non-installed tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
