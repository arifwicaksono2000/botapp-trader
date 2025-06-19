from twisted.internet import reactor
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402

def graceful_shutdown(bot):
    """
    Sends a logout request to the server to initiate a graceful disconnection.
    """
    print("[→] Sending logout request for a graceful shutdown...")
    request = ProtoOAAccountLogoutReq(ctidTraderAccountId=bot.account_id)
    bot.client.send(request)

def stop_reactor(bot, msg):
    """
    Handles the reconcile response. If no positions are open, it initiates
    a graceful shutdown instead of an abrupt reactor stop.
    """
    reconcile_res = Protobuf.extract(msg)
    # The 'position' field was renamed to 'positions' in some API versions.
    # Check for both to be safe.
    open_positions = getattr(reconcile_res, 'positions', []) or getattr(reconcile_res, 'position', [])

    if len(open_positions) == 0:
        print("[✓] Reconcile complete: Confirmed no open positions.")
        # Instead of stopping the reactor here, we now call for a graceful shutdown.
        graceful_shutdown(bot)
    else:
        print("[!!!] CRITICAL WARNING: Reconcile check failed. Unexpected open positions remain!")
        from google.protobuf.json_format import MessageToDict
        for pos in open_positions:
            print(MessageToDict(pos))

        print("[!] Halting bot due to unexpected account state.")
        # In this critical failure case, we might still want to stop abruptly.
        # Or, you could add an emergency "close all positions" function here.
        if reactor.running:
            reactor.stop()