# execution.py
import asyncio
import httpx
from ctrader_open_api import Protobuf
from twisted.internet.threads import deferToThread
from ..helpers import manage_segments

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402

def handle_spot_event(bot, msg):
    spot = Protobuf.extract(msg)
    print(f"RAW SPOT: ask={spot.ask}, bid={spot.bid}, timestamp={spot.timestamp}")

    # 1) update ask/bid
    _update_bid_ask(bot, spot.ask, spot.bid)

    # 2) compute midpoint if we have both sides | for fallback only
    # We still calculate based on ask and bid price individually
    
    if not _have_bid_ask(bot):
        print("[!] Missing ask or bid price, cannot compute latest price.")
        return
    _update_latest_price(bot)

    # 3) recalc PnL for all open positions
    for pid, pos in bot.positions.items():
        if pos["status"] != "OPEN":
            continue
        data = _build_pnl_payload(bot, pid, pos)
        print(data)
        asyncio.create_task(broadcast_position_update(data))
    
    # d = deferToThread(manage_segments, bot)
    
    # d.addCallback(lambda result: print("manage_segments completed."))
    # d.addErrback(lambda failure: print(f"manage_segments failed: {failure}"))


def _update_bid_ask(bot, raw_ask: int, raw_bid: int):
    if raw_ask > 0:
        bot.last_ask = raw_ask / 100_000.0
    if raw_bid > 0:
        bot.last_bid = raw_bid / 100_000.0

def _have_bid_ask(bot) -> bool:
    return getattr(bot, "last_ask", 0) and getattr(bot, "last_bid", 0)

def _update_latest_price(bot):
    bot.latest_price = (bot.last_ask + bot.last_bid) / 2

def _build_pnl_payload(bot, pid: int, pos: dict) -> dict:
    entry = pos["entry_price"]
    
    # The actual volume of the position that was opened/remains open
    actual_position_volume = pos["volume"] * 0.01

    # Determine the current price based on the position's trade side
    # This block now explicitly determines the correct `current_price_for_pnl`
    # and calculates `pnl_usd` within its respective branch.
    current_price_for_pnl = 0.0 # Initialize to avoid UnboundLocalError
    pnl_usd = 0.0 # Initialize PnL to 0.0
    
    if pos["tradeSide"] == ProtoOATradeSide.Value("BUY"): # LONG position
        current_price_for_pnl = bot.last_bid # If closing a BUY, you SELL at the BID
        pnl_usd = (current_price_for_pnl - entry) * actual_position_volume
        
    elif pos["tradeSide"] == ProtoOATradeSide.Value("SELL"): # SHORT position
        current_price_for_pnl = bot.last_ask # If closing a SELL, you BUY at the ASK
        pnl_usd = (entry - current_price_for_pnl) * actual_position_volume
        
    else:
        # Fallback for unexpected tradeSide (should ideally not be reached)
        # Log a warning and set PnL to 0 or use mid-price as a best guess
        print(f"[WARN] Unknown tradeSide for position {pid}: {pos.get('tradeSide', 'N/A')}. PnL set to 0.")
        current_price_for_pnl = bot.latest_price # As a fallback for display, use mid-price
        pnl_usd = 0.0

    # For display 'lot' will be actual volume / 100,000 (standard lots)
    display_lot = actual_position_volume / 100_000.0


    return {
        "positionId":    pid,
        "symbolId":      pos["symbolId"],
        "lot":           display_lot,
        "entry_price":   round(entry, 5),
        "price":         round(current_price_for_pnl, 5), # Use the specific price used for PnL
        "unrealisedPnL": round(pnl_usd, 2),
        "status":        pos["status"],
    }

async def broadcast_position_update(data):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:9000/broadcast", json=data)