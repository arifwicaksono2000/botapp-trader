from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from .trading import send_market_order

def after_app_auth(bot):
    print("[✓] App authenticated. Authorizing account…")
    req = ProtoOAAccountAuthReq(
        ctidTraderAccountId=bot.account_id,
        accessToken=bot.access_token
    )
    bot.client.send(req)

def after_account_auth(bot):
    print("[✓] Account authorized. Subscribing + sending order…")
    bot.client.send(ProtoOASubscribeSpotsReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=[bot.symbol_id],
        subscribeToSpotTimestamp=True,
    ))

    send_market_order(bot)   # ✅ call instance method
