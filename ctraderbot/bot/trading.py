# trading.py
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet import reactor

def send_market_order(bot):
    # Open a LONG
    req_long = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("BUY"),
        volume=bot.volume,
        clientOrderId="OPEN_LONG_1"
    )
    bot.client.send(req_long)

    # Open a SHORT
    req_short = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("SELL"),
        volume=bot.volume,
        clientOrderId="OPEN_SHORT_2"
    )
    bot.client.send(req_short)


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
