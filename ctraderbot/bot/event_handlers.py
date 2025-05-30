# event_handlers.py
import httpx
import asyncio

from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
# from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints  # noqa: E402
from ctrader_open_api import Protobuf
from twisted.internet import reactor
from google.protobuf.json_format import MessageToDict
from .auth import after_app_auth, after_account_auth
from .execution import handle_execution
from ..settings import CLIENT_ID, CLIENT_SECRET
import datetime as dt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def register_callbacks(bot):
    bot.client.setConnectedCallback(lambda _: on_connected(bot))
    bot.client.setDisconnectedCallback(lambda _, r: on_disconnected(r))
    bot.client.setMessageReceivedCallback(lambda _, m: on_message(bot, m))

def on_connected(bot):
    print("[+] Connected. Authenticating app…")
    req = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
    bot.client.send(req)

def on_disconnected(reason):
    print("[-] Disconnected:", reason)
    if reactor.running:
        reactor.stop()

async def broadcast_position_update(data):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:9000/broadcast", json=data)


def on_message(bot, msg):
    pt = msg.payloadType
    print(f"[debug] Incoming payloadType = {pt}")

    if pt == ProtoOAApplicationAuthRes().payloadType:
        after_app_auth(bot)
    elif pt == ProtoOAAccountAuthRes().payloadType:
        after_account_auth(bot)
    # elif pt == ProtoOAPositionUpdateEvent().payloadType:
    #     on_position_update(bot, Protobuf.extract(msg))
    elif pt == ProtoOAExecutionEvent().payloadType:
        handle_execution(bot, Protobuf.extract(msg))
    elif pt == ProtoOAReconcileRes().payloadType:
        print("[✓] Reconcile complete. Exiting…")
        reactor.stop()
    elif pt == ProtoOASpotEvent().payloadType:
        spot = Protobuf.extract(msg)

        # 1) Update last-known ask/bid (divide by 100_000 to get actual price)
        if spot.ask > 0:
            bot.last_ask = spot.ask / 100000.0
        if spot.bid > 0:
            bot.last_bid = spot.bid / 100000.0

        # 2) Only compute midpoint when you have both
        if bot.last_ask and bot.last_bid:
            bot.latest_price = (bot.last_ask + bot.last_bid) / 2
        else:
            print("[!] Missing ask or bid price, cannot compute latest price.")
            return   # or `continue` the surrounding loop so you skip PnL

        # 3) Recalculate PnL for each open position
        for pid, p in bot.positions.items():
            print(f"Entry Price: {p['entry_price']}")
            if p["status"] != "OPEN":
                continue

            # convert entry price and volume
            entry = p["entry_price"]
            lots  = p["volume"]      / (100000 * 100) # p volume is 100.000

            pip_diff = (bot.latest_price - entry)
            # pip_value = 10  # for 1 lot
            pnl = pip_diff * p["volume"] * 0.01

            data = {
                "positionId":   pid,
                "symbolId":     p["symbolId"],
                "Lot":       lots,
                "entry_price": round(entry, 5),
                "price": round(bot.latest_price, 5),
                "unrealisedPnL": f"{round(pnl, 2):.2f}",  # Force two decimals
                # "unrealisedPnL": round(pnl, 2),
                "status":       p["status"],
            }

            print(data)
            asyncio.create_task(broadcast_position_update(data))

    elif pt in {ProtoOAOrderErrorEvent().payloadType, ProtoOAErrorRes().payloadType}:
        print("[✖] Server error:", MessageToDict(Protobuf.extract(msg)))
        if reactor.running:
            reactor.stop()
    else:
        print(MessageToDict(Protobuf.extract(msg)))
