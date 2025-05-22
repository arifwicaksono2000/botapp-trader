#!/usr/bin/env python3
"""
bot_api.py – runs the trading bot *and* exposes a FastAPI control layer
"""
from dotenv import load_dotenv
from pathlib import Path
import os, threading, subprocess, uuid
from fastapi import FastAPI, HTTPException, Header
import uvicorn
import subprocess
import uuid
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# --- import your existing stuff --------------------------------
from main import SimpleBot, build_parser, loop, Base, fetch_access_token
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
# ----------------------------------------------------------------

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)
# load_dotenv(dotenv_path=env_path)

# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djbotapp.settings")
# django.setup()

BOT_TOKEN = os.getenv("BOT_API_TOKEN")   # shared with Django
BOT_STATUS = {"state": "idle"}                         # idle | running | error

app = FastAPI(title="Trading-Bot API")

# Track all active subprocesses
active_bots = {}

def require_token(auth: str):
    if auth != f"Bearer {BOT_TOKEN}":
        raise HTTPException(status_code=401, detail="Bad token")


def broadcast_trades():
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        "bot_status",
        {
            "type": "send_status",
            "data": {
                tid: {
                    "side": info["side"],
                    "volume": info["volume"],
                    "hold": info["hold"],
                    "status": "running" if info["process"].poll() is None else "completed",
                    "pid": info["process"].pid
                }
                for tid, info in active_bots.items()
            }
        }
    )

@app.get("/status")
def status(authorization: str = Header(None)):
    require_token(authorization)

    statuses = {}
    for trade_id, info in active_bots.items():
        process = info["process"]
        statuses[trade_id] = {
            "side": info["side"],
            "volume": info["volume"],
            "hold": info["hold"],
            "status": "running" if process.poll() is None else "completed",
            "pid": process.pid
        }

    return statuses

@app.post("/start")
async def start(
    side: str = "buy",
    volume: int = 1000,
    hold: int = 60,
    authorization: str = Header(None)
):
    require_token(authorization)

    # spawn subprocess exactly as before
    BOT_PATH = Path(__file__).resolve().parent
    PY = BOT_PATH / "trenv" / "bin" / "python"
    cmd = [str(PY), "main.py", "--side", side, "--volume", str(volume), "--hold", str(hold)]
    p = subprocess.Popen(cmd, cwd=str(BOT_PATH))

    trade_id = str(uuid.uuid4())
    active_bots[trade_id] = {"process": p, "side": side, "volume": volume, "hold": hold}

    # broadcast “new trade started”
    broadcast_trades()

    # monitor thread will wait for this subprocess to exit
    def monitor():
        p.wait()
        # once done, update status & rebroadcast
        broadcast_trades()

    threading.Thread(target=monitor, daemon=True).start()
    return {"trade_id": trade_id}


@app.post("/stop")
def emergency_stop(authorization: str = Header(None)):
    require_token(authorization)
    # you expose a method on SimpleBot to close positions
    if SimpleBot.instance:
        SimpleBot.instance._close_position()
        return {"msg": "close command sent"}
    raise HTTPException(409, "Bot not running")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
