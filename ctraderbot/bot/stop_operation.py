from twisted.internet import reactor
from ctrader_open_api import Protobuf

def stop_reactor(bot, msg):
    reconcile_res = Protobuf.extract(msg)
    open_positions = reconcile_res.position

    # --- ADD THIS LOGIC ---
    if len(open_positions) == 0:
        print("[✓] Reconcile complete: Confirmed no open positions. Exiting safely.")
        reactor.stop()
    else:
        print("[!!!] CRITICAL WARNING: Reconcile check failed. Unexpected open positions remain!")
        for pos in open_positions:
            # Using MessageToDict to cleanly print the unexpected position details
            from google.protobuf.json_format import MessageToDict
            print(MessageToDict(pos))
        
        print("[!] Halting bot due to unexpected account state.")
        # In a more advanced implementation, you might trigger an
        # emergency close_all() function here instead of stopping.
        # reactor.stop()