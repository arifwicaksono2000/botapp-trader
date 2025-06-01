from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOASpotEvent
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAPackage
import datetime as dt

def make_fake_spot_event(symbol_id, bid, ask, timestamp_ms=None):
    ev = ProtoOASpotEvent(
        symbolId=symbol_id,
        bid=bid,
        ask=ask,
        tickTimestamp=timestamp_ms or int(dt.datetime.utcnow().timestamp() * 1000)
    )
    pkg = ProtoOAPackage()
    pkg.payloadType = ev.payloadType
    pkg.payload = ev.SerializeToString()
    return pkg
