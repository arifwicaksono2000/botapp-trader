from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOASubscribeReq,
)
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
    bot.client.send(ProtoOASubscribeReq(
        ctidTraderAccountId=bot.account_id,
        subscribeSpots=True,
        subscribeOrders=True,
        subscribePositions=True
    ))

    send_market_order(bot)   # ✅ call instance method
