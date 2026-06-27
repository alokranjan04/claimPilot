"""Standalone worker entrypoint for Container Apps deployment.

Boots the background claim-processing worker against the configured
provider set (``PROVIDER`` env var) and runs until terminated.  Reuses
the existing ``run_worker`` loop — this module just wires up the DI
and graph, then hands off.

Usage::

    python -m claimpilot.api.worker_main

In a Container App, set the command override to::

    python -m claimpilot.api.worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from claimpilot.api.worker import ClaimStore, EventBus, run_worker
from claimpilot.graph.build_graph import build_graph
from claimpilot.infra.di import create_providers
from claimpilot.infra.settings import Settings
from claimpilot.observability.logging import configure_logging, get_logger


async def _main() -> None:
    """Wire providers, build the graph, and run the worker loop."""
    configure_logging()
    log = get_logger()
    log.info("worker_starting", provider=Settings().provider)

    settings = Settings()
    providers = create_providers(settings)

    graph = build_graph(settings, llm=providers.llm)

    store = ClaimStore(providers.checkpointer)
    bus = EventBus()

    # Graceful shutdown on SIGTERM / SIGINT.
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _signal_handler() -> None:
        log.info("worker_shutdown_signal")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler; use signal.signal instead.
            signal.signal(sig, lambda *_: _signal_handler())

    worker_task = asyncio.create_task(run_worker(providers.queue, store, bus, graph))

    log.info("worker_running", queue_type=type(providers.queue).__name__)
    await stop.wait()

    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task

    log.info("worker_stopped")


def main() -> None:
    """Sync entry point."""
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())
    sys.exit(0)


if __name__ == "__main__":
    main()
