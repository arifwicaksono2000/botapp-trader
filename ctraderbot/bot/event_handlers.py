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
from .stop_operation import stop_reactor
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
        stop_reactor(bot, msg)
    elif pt == ProtoOAAccountLogoutRes().payloadType:
        print("[Info] Logout confirmed by server. Connection will be closed shortly.")
    elif pt == ProtoOAAccountDisconnectEvent().payloadType:
        print("[Info] Account disconnected by server.")
        on_disconnected("Server sent a disconnect event.")
    elif pt in {ProtoOAOrderErrorEvent().payloadType, ProtoOAErrorRes().payloadType}:
        err = Protobuf.extract(msg)
        print("[✖] Server error:", MessageToDict(Protobuf.extract(msg)))
        stop_reactor(bot, msg)

        # Insert this "if" block to catch the MARKET_CLOSED error
        # if getattr(err, 'errorCode', '') == 'MARKET_CLOSED':
        #     print(f"[INFO] Market is closed. The bot cannot place new trades.")
        #     print("[INFO] Initiating a graceful shutdown.")
        #     stop_reactor(bot, msg)
        #     return # Exit the function
    
        # if reactor.running:
        #     reactor.stop()
    else:
        elseError = MessageToDict(Protobuf.extract(msg))
        print("[✖] Unhandled error:", elseError)
