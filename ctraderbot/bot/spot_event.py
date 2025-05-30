# execution.py
import asyncio
import httpx
from ctrader_open_api import Protobuf


def handle_spot_event(bot, msg):
    spot = Protobuf.extract(msg)

    # 1) update ask/bid
    _update_bid_ask(bot, spot.ask, spot.bid)

    # 2) compute midpoint if we have both sides
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
    entry   = pos["entry_price"]
    units   = pos["volume"] * 0.01 # I have no idea what is this 0.01, but it works
    current = bot.latest_price
    pnl_usd = (current - entry) * units

    return {
        "positionId":    pid,
        "symbolId":      pos["symbolId"],
        "Lot":           units / 100_000.0,
        "entry_price":   round(entry, 5),
        "price":         round(current, 5),
        "unrealisedPnL": f"{pnl_usd:.2f}",
        "status":        pos["status"],
    }

async def broadcast_position_update(data):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:9000/broadcast", json=data)