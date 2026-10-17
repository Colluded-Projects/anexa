"""Embedded FalkorDB for local development without Docker.

`uv run orgraph-devdb` starts a FalkorDB server (via falkordblite) listening on
ORGRAPH_FALKORDB_HOST:ORGRAPH_FALKORDB_PORT and keeps it running until
interrupted. It is a real Redis server, so it also works as the Celery broker.
Data is kept in ./.orgraph/dev.db. Use the Docker image for anything shared.
"""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

from .config import get_settings


def main() -> None:
    try:
        from redislite.falkordb_client import FalkorDB
    except ImportError:
        sys.exit("falkordblite is not installed; run `uv sync` (it is a dev dependency)")

    settings = get_settings()
    data = Path(".orgraph")
    data.mkdir(exist_ok=True)
    db = FalkorDB(
        str(data / "dev.db"),
        serverconfig={"port": str(settings.falkordb_port), "bind": settings.falkordb_host},
    )
    db.select_graph("orgraph_probe").query("RETURN 1")
    print(
        f"FalkorDB listening on {settings.falkordb_host}:{settings.falkordb_port} "
        f"(data in {data / 'dev.db'}). Ctrl-C to stop.",
        flush=True,
    )

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()


if __name__ == "__main__":
    main()
