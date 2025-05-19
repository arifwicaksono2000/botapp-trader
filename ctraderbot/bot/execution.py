# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from ..helpers import insert_deal
from .trading import close_position, reconcile

def handle_execution(bot, ev):
    print("[✓] Execution Event:")
    if not ev.HasField("position"):
        print("No position in event.")
        return
    print(f"  executionType: {ev.executionType}")
    deal, order, pos = ev.deal, ev.order, ev.position

    pos = ev.position
    pid = pos.positionId
    entry = pos.price / 100000.0

    bot.positions[pid] = {
        "symbolId": pos.tradeData.symbolId,
        "volume": pos.tradeData.volume,
        "entry_price": entry,
        "used_margin": pos.usedMargin,
        "swap": pos.swap,
        "timestamp": dt.datetime.utcnow().isoformat(),
        "status": "OPEN" if pos.positionStatus == 1 else "CLOSED",
    }

    # data = {
    #     "deal_id": deal.dealId,
    #     "position_id": pos.positionId,
    #     "order_id": order.orderId,
    #     "side": order.tradeData.tradeSide,
    #     "volume": deal.volume,
    #     "price": deal.executionPrice,
    #     "commission": deal.commission,
    #     "swap": pos.swap,
    #     "used_margin": pos.usedMargin,
    #     "execution_type": ev.executionType,
    #     "timestamp": dt.datetime.utcnow(),
    # }

    print(f"[TRACK] Pos {pid} | Sym {pos.tradeData.symbolId} | Vol {pos.tradeData.volume} | "
        f"Entry={entry} | Margin={pos.usedMargin} | Status={bot.positions[pid]['status']}")

    # ensureDeferred(insert_deal(data))

    if ev.executionType == ProtoOAExecutionType.ORDER_FILLED:
        if bot.open_position_id is None:  # first fill (open)
            bot.open_position_id = pos.positionId
            print(f"[→] Position opened {bot.open_position_id}. Hold {bot.hold}s…")
            from twisted.internet import reactor
            reactor.callLater(bot.hold, close_position, bot)
        else:  # second fill (close)
            print(f"[✓] Position {bot.open_position_id} closed.")
            reconcile(bot)
