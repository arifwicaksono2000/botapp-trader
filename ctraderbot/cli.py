# file: ctraderbot/cli.py
"""Command-line entry-point. Run with `python -m ctraderbot.cli --hold 60`."""
from __future__ import annotations

def main():
    """
    Main function to set up and run the trading bot.
    Handles reactor installation, database bootstrapping, and bot initialization.
    """
    # --- Step 1: Install the reactor FIRST. ---
    # This must be the absolute first thing that happens before any other
    # module that might use Twisted is imported.
    from .bridge import setup_asyncio_reactor
    loop = setup_asyncio_reactor()

    # --- Step 2: Now that the reactor is installed, import everything else. ---
    import argparse
    from ctrader_open_api import Client, TcpProtocol
    from .helpers import fetch_access_token, fetch_main_account
    from .settings import HOST, PORT, SYMBOL_ID
    from .bot.simple_bot import SimpleBot
    from .database import engine, Base

    # --- Step 3: Proceed with the rest of the application logic. ---
    parser = argparse.ArgumentParser(description="Async cTrader bot CLI")
    parser.add_argument("--hold", type=int, default=60, help="Hold duration in seconds")
    args = parser.parse_args()

    # DB bootstrap
    async def bootstrap():
        """
        Initializes database schema and fetches essential credentials.
        """
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Fetch both the primary key and the cTrader account ID
        account_pk, account_id = await fetch_main_account()
        # Fetch the access token
        token = await fetch_access_token()
        
        return token, account_pk, account_id

    print("[DEBUG] Bootstrapping DB and fetching token...")
    token, account_pk, account_id = loop.run_until_complete(bootstrap())

    print(f"[DEBUG] Token retrieved | Account PK: {account_pk} | Account ID: {account_id}")

    # Start the bot
    client = Client(HOST, PORT, TcpProtocol)
    bot = SimpleBot(client, token, account_pk, account_id, SYMBOL_ID, args.hold)
    
    print("[DEBUG] Bot initialized, starting reactor...")
    bot.start()


if __name__ == "__main__":
    main()