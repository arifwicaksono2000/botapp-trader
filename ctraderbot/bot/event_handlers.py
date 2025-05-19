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
from .trading import on_position_update
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
        # bot.latest_price = (spot.ask + spot.bid) / 2  # midpoint price
        ask = spot.ask / 100000.0
        bid = spot.bid / 100000.0
        bot.latest_price = (ask + bid) / 2
        # Recalculate PnL for each open position
        for pid, p in bot.positions.items():
            if p["status"] == "OPEN":
                entry = p["entry_price"]
                volume = p["volume"]
                diff = bot.latest_price - entry
                pnl = (diff * volume / 100000)

                data = {
                    "positionId": pid,
                    "symbolId": p["symbolId"],
                    "volume": volume,
                    "entry_price": entry,
                    "price": bot.latest_price,
                    "unrealisedPnL": round(pnl, 2),
                    "status": p["status"],
                }

                print(data)

                asyncio.create_task(broadcast_position_update(data))


    elif pt in {ProtoOAOrderErrorEvent().payloadType, ProtoOAErrorRes().payloadType}:
        print("[✖] Server error:", MessageToDict(Protobuf.extract(msg)))
        if reactor.running:
            reactor.stop()
    else:
        print(MessageToDict(Protobuf.extract(msg)))

def on_position_update(bot, update):
    for pos in update.position:
        pos_id = pos.positionId
        bot.positions[pos_id] = {
            "symbolId": pos.symbolId,
            "volume": pos.volume,
            "unrealisedNetProfit": pos.unrealisedNetProfit,
            "usedMargin": pos.usedMargin,
            "swap": pos.swap,
            "timestamp": dt.datetime.utcnow().isoformat()
        }
        print(
            f"[TRACK] Pos {pos_id} | Sym {pos.symbolId} | Vol {pos.volume} | "
            f"PnL {pos.unrealisedNetProfit:.2f} | Margin {pos.usedMargin}"
        )
