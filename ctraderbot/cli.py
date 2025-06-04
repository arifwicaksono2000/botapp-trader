# file: ctrader_bot/cli.py ------------------------------------------------------
"""Command-line entry-point. Run with `python -m ctrader_bot.cli …`."""
from __future__ import annotations
import argparse
import sys
import asyncio

# -----------------------------------------------------------------------------
# Twisted↔︎asyncio reactor bridging (platform‑safe)
# -----------------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from twisted.internet import asyncioreactor  # noqa: E402
asyncioreactor.install(loop)                  # must be before importing reactor
# from twisted.internet import reactor          # noqa: E402

# Only now is it safe to import Twisted-dependent modules
from ctrader_open_api import Client, TcpProtocol

from .database import engine, Base
from .helpers import fetch_access_token, fetch_main_account
from .settings import HOST, PORT, ACCOUNT_ID, SYMBOL_ID
from .bot.simple_bot import SimpleBot


def build_parser():
    parser = argparse.ArgumentParser(description="Async cTrader bot CLI")
    # parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--volume", type=int, default=1000, help="Volume in micro-lots")
    parser.add_argument("--hold", type=int, default=60, help="Hold duration in seconds")
    return parser


def main():
    args = build_parser().parse_args()

    # Setup asyncio ↔︎ Twisted bridge
    # loop = setup_asyncio_reactor()

    # DB bootstrap
    async def bootstrap():
        # Create tables once
        # async with engine.begin() as conn:
        #     await conn.run_sync(Base.metadata.create_all)

        # Run both fetches in parallel
        token_task = fetch_access_token()
        account_task = fetch_main_account()

        token, account_id = await asyncio.gather(token_task, account_task)
        return token, account_id

    print("[DEBUG] Bootstrapping DB and fetching token...")
    token, account_id = loop.run_until_complete(bootstrap())

    print(f"[DEBUG] Token: {token}… | Account ID: {account_id}")
    # Start the bot
    # print(ACCOUNT_ID, HOST)
    client = Client(HOST, PORT, TcpProtocol)
    bot = SimpleBot(client, token, account_id, SYMBOL_ID, args.volume, args.hold)
    # bot = SimpleBot(client, token, ACCOUNT_ID, SYMBOL_ID, args.volume, args.hold)
    # bot = SimpleBot(client, token, ACCOUNT_ID, SYMBOL_ID, args.side, args.volume, args.hold)
    print("[DEBUG] Bot initialized, starting reactor...")
    bot.start()


if __name__ == "__main__":
    main()