# event_handlers.py

from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
# from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints  # noqa: E402
from ctrader_open_api import Protobuf
from twisted.internet import reactor
from google.protobuf.json_format import MessageToDict
from .auth import after_app_auth, after_account_auth
from .execution import handle_execution
from .pnl_event import handle_pnl_event
# from .spot_event import handle_spot_event
from ..settings import CLIENT_ID, CLIENT_SECRET

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

def on_message(bot, msg):
    pt = msg.payloadType
    print(f"[debug] Incoming payloadType = {pt}")

    if pt == ProtoOAApplicationAuthRes().payloadType:
        after_app_auth(bot)
    elif pt == ProtoOAAccountAuthRes().payloadType:
        after_account_auth(bot)
    # elif pt == ProtoOAPositionUpdateEvent().payloadType:
    #     on_position_update(bot, Protobuf.extract(msg))
    elif pt == ProtoOAGetPositionUnrealizedPnLRes().payloadType:
        handle_pnl_event(bot, msg)
        
    elif pt == ProtoOAExecutionEvent().payloadType:
        handle_execution(bot, Protobuf.extract(msg))
    elif pt == ProtoOAReconcileRes().payloadType:
        print("[✓] Reconcile complete. Exiting…")
        # print("[INFO] Reconcile Data:", MessageToDict(Protobuf.extract(msg)))
        reactor.stop()

    # elif pt == ProtoOASpotEvent().payloadType:
    #     handle_spot_event(bot, msg)
    elif pt in {ProtoOAOrderErrorEvent().payloadType, ProtoOAErrorRes().payloadType}:
        print("[✖] Server error:", MessageToDict(Protobuf.extract(msg)))
        if reactor.running:
            reactor.stop()
    else:
        print(MessageToDict(Protobuf.extract(msg)))
