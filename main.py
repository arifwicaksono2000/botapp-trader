# file: run_bot_with_api.py
"""
Main entry point to run the cTrader bot and the FastAPI control server together.
"""
import os
import uvicorn
import threading
from fastapi import FastAPI, Header, HTTPException
from fastapi import FastAPI

# --- Only import what's needed for the reactor setup and FastAPI app ---
from ctraderbot.bridge import setup_asyncio_reactor


# --- Main Application Setup ---

# This global variable will hold our single bot instance
# We define it here so the API endpoint can access it.
bot_instance: "SimpleBot" = None

# 1. Set up the FastAPI app
app = FastAPI(title="cTrader Bot Control API")


@app.post("/emergency-stop")
async def emergency_stop(authorization: str = Header(None)):
    """
    API endpoint to trigger the emergency stop of all trades.
    Requires a secret token for authorization.
    """
    from twisted.internet import reactor
    from ctraderbot.settings import BOT_API_TOKEN

    if authorization != f"Bearer {BOT_API_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    if not bot_instance or not reactor.running:
        raise HTTPException(status_code=503, detail="Bot is not currently running.")
    
    # Safely call the bot's method from the API's thread into the bot's (Twisted) thread
    reactor.callFromThread(bot_instance.emergency_stop_all_trades)
    
    return {"status": "ok", "message": "Emergency stop signal sent to the bot."}


def run_api_server():
    """Function to run the Uvicorn server in a separate thread."""
    uvicorn.run(app, host="0.0.0.0", port=9000)

def main():
    """
    Initializes and starts both the cTrader bot and the API server.
    """
    # global bot_instance

    # --- Step 1: Install the reactor FIRST. ---
    loop = setup_asyncio_reactor()

    # --- Step 2: Now that the reactor is installed, import everything else. ---
    from ctrader_open_api import Client, TcpProtocol
    from ctraderbot.bot.simple_bot import SimpleBot
    from ctraderbot.database import engine, Base
    from ctraderbot.helpers import fetch_access_token, fetch_main_account
    from ctraderbot.settings import HOST, PORT, SYMBOL_ID

    # --- Step 3: DB bootstrap ---
    async def bootstrap():
        """
        Initializes database schema and fetches essential credentials.
        """
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        account_pk, account_id = await fetch_main_account()
        token = await fetch_access_token()
        return token, account_pk, account_id

    print("[DEBUG] Bootstrapping DB and fetching token...")
    token, account_pk, account_id = loop.run_until_complete(bootstrap())
    print(f"[DEBUG] Token retrieved | Account PK: {account_pk} | Account ID: {account_id}")

    # --- Step 4: Create the bot instance ---
    client = Client(HOST, PORT, TcpProtocol)
    # Note: We call SimpleBot with the correct number of arguments here.
    bot_instance = SimpleBot(client, token, account_pk, account_id, SYMBOL_ID)
    
    # --- Step 5: Start API and Bot ---
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    print("🚀 FastAPI control server started in background on port 9000.")

    # Start the bot's main event loop (this will block until the bot stops)
    print("🤖 cTrader bot starting...")
    bot_instance.start()
    print("✅ Bot has shut down gracefully.")


if __name__ == "__main__":
    main()