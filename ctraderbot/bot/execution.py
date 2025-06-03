# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
# from ..helpers import insert_deal
from .trading import close_position, reconcile
from twisted.internet import reactor
from functools import partial

def handle_execution(bot, ev):
    print("[✓] Execution Event:")
    if not ev.HasField("position"):
        print("No position in event.")
        return

    order = ev.order
    pos = ev.position
    pid = pos.positionId
    coid = order.clientOrderId or ""
    side = order.tradeData.tradeSide         # 1 = BUY, 2 = SELL
    entry_price = pos.price
    used_margin = pos.usedMargin
    status_str = "OPEN" if pos.positionStatus == 1 else "CLOSED"

    # Record/update the position
    bot.positions[pid] = {
        "symbolId": pos.tradeData.symbolId,
        "volume": pos.tradeData.volume,
        "entry_price": entry_price,
        "used_margin": used_margin,
        "swap": pos.swap,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status_str,
        "side": side,
        "clientOrderId": coid
    }

    print(f"[TRACK] Pos {pid} | Side={ 'BUY' if side==1 else 'SELL' } "
          f"| Vol {pos.tradeData.volume} | Entry={entry_price} | "
          f"Margin={used_margin} | Status={status_str} | coid={coid}")

    if ev.executionType != ProtoOAExecutionType.ORDER_FILLED:
        return

    # ─────── OPEN LONG ───────
    if coid == "OPEN_LONG_1":
        bot.open_long_id = pid
        bot.positions[pid]["status"] = "OPEN"
        print(f"[→] Long-opened {pid}. Hold {bot.hold}s…")
        reactor.callLater(bot.hold, close_position, bot, pid)
        return

    # ─────── OPEN SHORT ───────
    if coid == "OPEN_SHORT_2":
        bot.open_short_id = pid
        bot.positions[pid]["status"] = "OPEN"
        print(f"[→] Short-opened {pid}. Hold {bot.hold}s…")
        reactor.callLater(bot.hold, close_position, bot, pid)
        return

    # ─────── CLOSE LONG ───────
    # A sell with volume 0 on your long’s position_id means “long closed”
    if pid == getattr(bot, "open_long_id", None) \
       and side == ProtoOATradeSide.Value("SELL") \
       and pos.tradeData.volume == 0:

        bot.positions[pid]["status"] = "CLOSED"
        print(f"[✓] Closed Long {pid} (SELL)")

        # If the short is already closed, reconcile now
        short_id = getattr(bot, "open_short_id", None)
        if short_id and bot.positions.get(short_id, {}).get("status") == "CLOSED":
            print("[→] Sell sides closed → reconciling now…")
            reconcile(bot)
        return

    # ─────── CLOSE SHORT ───────
    # A buy with volume 0 on your short’s position_id means “short closed”
    if pid == getattr(bot, "open_short_id", None) \
       and side == ProtoOATradeSide.Value("BUY") \
       and pos.tradeData.volume == 0:

        bot.positions[pid]["status"] = "CLOSED"
        print(f"[✓] Closed Short {pid} (BUY)")

        # If the long is already closed, reconcile now
        long_id = getattr(bot, "open_long_id", None)
        if long_id and bot.positions.get(long_id, {}).get("status") == "CLOSED":
            print("[→] Buy sides closed → reconciling now…")
            reconcile(bot)
        return

    # ─────── Anything else ───────
    # (e.g. partial fills or stray orders—just log them)
    print(f"[i] Unhandled ORDER_FILLED for pid={pid}, coid={coid}")


def close_all_positions(bot):
    """Close every open position we know about."""
    for position_id, info in list(bot.positions.items()):
        if info["status"] == "OPEN":
            close_position(bot, position_id)
