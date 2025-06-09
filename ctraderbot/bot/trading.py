# trading.py
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet import reactor
from ..helpers import fetch_milestone
from twisted.internet.threads import deferToThread

def send_market_order(bot):
    """
    Schedule a synchronous DB lookup in a thread, then—when that completes—
    send two market orders (long + short).
    """
    # Defer the DB lookup to a thread
    d = deferToThread(fetch_milestone, bot.account_id)

    def on_result(result):
        balance, milestone = result

        # if milestone:
        #     info = {
        #         "id": milestone.id,
        #         "starting_balance": float(milestone.starting_balance),
        #         "loss": float(milestone.loss),
        #         "profit_goal": float(milestone.profit_goal),
        #         "lot_size": float(milestone.lot_size),
        #         "curr_lot": bot.volume,
        #         "ending_balance": float(milestone.ending_balance),
        #     }
        #     print("[MILESTONE]", info)
        # else:
        #     print(f"[MILESTONE] No matching milestone row for balance {balance}")

        lot_size = milestone.lot_size * 100 * 100000
        lot_size = int(lot_size)

        # lot_size = 3600000
        
        print("[MILESTONE]", milestone.lot_size)
        print("[LOT SIZE]", lot_size)

        # print(lot_size, bot.volume)

        # Now that the DB lookup is done, send the two market orders:

        # — Open a LONG (BUY)
        req_long = ProtoOANewOrderReq(
            ctidTraderAccountId=bot.account_id,
            symbolId=bot.symbol_id,
            orderType=ProtoOAOrderType.MARKET,
            tradeSide=ProtoOATradeSide.Value("BUY"),
            volume=lot_size,
            # volume=bot.volume,
            clientOrderId="OPEN_LONG_1"
        )
        bot.client.send(req_long)

        # — Open a SHORT (SELL)
        req_short = ProtoOANewOrderReq(
            ctidTraderAccountId=bot.account_id,
            symbolId=bot.symbol_id,
            orderType=ProtoOAOrderType.MARKET,
            tradeSide=ProtoOATradeSide.Value("SELL"),
            volume=lot_size,
            # volume=bot.volume,
            clientOrderId="OPEN_SHORT_2"
        )
        bot.client.send(req_short)

    d.addCallback(on_result)
    d.addErrback(lambda failure: print("[DB error]", failure))


def close_position(bot, position_id):
    if position_id is None:
        print("[!] No open position to close.")
        return

    print(f"[→] Closing position {position_id}…")
    req = ProtoOAClosePositionReq(
        ctidTraderAccountId=bot.account_id,
        positionId=position_id,
        volume=bot.volume,
        # mode=ProtoOAClosePositionMode.MARKET  # or whatever mode you prefer
    )
    d = bot.client.send(req)
    d.addErrback(lambda f: print("[✖] Close failed:", f))



def reconcile(bot):
    bot.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot.account_id))
