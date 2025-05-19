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
    print(f"  executionType: {ev.executionType}")
    deal, order, pos = ev.deal, ev.order, ev.position

    data = {
        "deal_id": deal.dealId,
        "position_id": pos.positionId,
        "order_id": order.orderId,
        "side": order.tradeData.tradeSide,
        "volume": deal.volume,
        "price": deal.executionPrice,
        "commission": deal.commission,
        "swap": pos.swap,
        "used_margin": pos.usedMargin,
        "execution_type": ev.executionType,
        "timestamp": dt.datetime.utcnow(),
    }

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
