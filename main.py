# file: run_bot_with_api.py
"""
Main entry point to run the cTrader bot and the FastAPI control server together.
"""
import os
import uvicorn
import threading
from fastapi import FastAPI, Header, HTTPException
from twisted.internet import reactor
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio

# --- Import all the necessary parts from your existing bot ---
from ctraderbot.bridge import setup_asyncio_reactor
from ctraderbot.bot.simple_bot import SimpleBot
from ctraderbot.database import engine, Base
from ctraderbot.helpers import fetch_access_token, fetch_main_account
from ctraderbot.settings import HOST, PORT, SYMBOL_ID, BOT_API_TOKEN

# --- Main Application Setup ---

# This global variable will hold our single bot instance
bot_instance: SimpleBot = None

# 1. Set up the FastAPI app
app = FastAPI(title="cTrader Bot Control API")

####### WEBSOCKET SYNTAX START ##########
# class ConnectionManager:
#     def __init__(self):
#         self.active_connections: list[WebSocket] = []

#     async def connect(self, websocket: WebSocket):
#         try:
#             await websocket.accept()
#             self.active_connections.append(websocket)
#         except Exception as e:
#             print(f"[!] WebSocket accept failed: {e}")


#     async def disconnect(self, websocket: WebSocket):
#         self.active_connections.remove(websocket)

#     async def broadcast(self, data: dict):
#         to_remove = []
#         for connection in self.active_connections:
#             try:
#                 await connection.send_json(data)
#             except RuntimeError:
#                 # Client already disconnected
#                 to_remove.append(connection)
#             except Exception as e:
#                 print(f"[!] Unexpected WebSocket error: {e}")
#                 to_remove.append(connection)
#         for conn in to_remove:
#             # In some versions of FastAPI/Starlette, this can error if already disconnected
#             # So we just remove it from our list.
#             if conn in self.active_connections:
#                self.active_connections.remove(conn)


# manager = ConnectionManager()

# @app.websocket("/ws/positions")
# async def positions_stream(websocket: WebSocket):
#     await manager.connect(websocket)
#     try:
#         while True:
#             # Keep the connection alive
#             await websocket.receive_text()
#     except WebSocketDisconnect:
#         await manager.disconnect(websocket)

# @app.post("/broadcast")
# async def broadcast_endpoint(data: dict):
#     await manager.broadcast(data)
#     return {"status": "sent", "data": data}

####### WEBSOCKET SYNTAX END ##########

@app.post("/emergency-stop")
async def emergency_stop(authorization: str = Header(None)):
    """
    API endpoint to trigger the emergency stop of all trades.
    Requires a secret token for authorization.
    """
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
    global bot_instance

    # --- Step 1: Install the reactor FIRST. ---
    # This is copied directly from your cli.py main function
    # Note: Imports are moved to the top of the run_bot_with_api.py file
    loop = setup_asyncio_reactor()

    # --- Step 2: Proceed with the rest of the application logic. ---
    # The --hold argument is no longer needed for continuous operation.

    # --- Step 3: DB bootstrap ---
    # This is the same async bootstrap function from cli.py
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
    # This creates the bot and assigns it to the global variable for the API
    from ctrader_open_api import Client, TcpProtocol
    client = Client(HOST, PORT, TcpProtocol)
    bot_instance = SimpleBot(client, token, account_pk, account_id, SYMBOL_ID)
    
    # --- Step 5: Start API and Bot ---
    # Start the FastAPI server in a background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    print("🚀 FastAPI control server started in background on port 9000.")

    # Start the bot's main event loop (this will block until the bot stops)
    print("🤖 cTrader bot starting...")
    bot_instance.start()
    print("✅ Bot has shut down gracefully.")


if __name__ == "__main__":
    main()