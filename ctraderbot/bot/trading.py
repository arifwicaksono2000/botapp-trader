# trading.py
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet import reactor

def send_market_order(bot):
    req = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("BUY"),
        volume=bot.volume,
    )
    bot.client.send(req)

    req = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("SELL"),
        volume=bot.volume,
    )
    bot.client.send(req)

def close_position(bot):
    if bot.open_position_id is None:
        print("[!] No open position to close.")
        return
    print("[→] Closing position…")
    req = ProtoOAClosePositionReq(
        ctidTraderAccountId=bot.account_id,
        positionId=bot.open_position_id,
        volume=bot.volume,
    )
    d = bot.client.send(req)
    d.addErrback(lambda f: print("[✖] Close failed:", f))

def reconcile(bot):
    bot.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot.account_id))
