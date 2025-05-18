"""Platform‑independent Twisted↔︎asyncio reactor setup."""
from __future__ import annotations
import asyncio
import sys


def setup_asyncio_reactor() -> asyncio.AbstractEventLoop:
    """Install the AsyncIO reactor and return the fresh event‑loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Must install BEFORE importing twisted.internet.reactor
    from twisted.internet import asyncioreactor  # pylint: disable=import-error

    asyncioreactor.install(loop)

    return loop