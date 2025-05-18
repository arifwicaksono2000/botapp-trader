"""Asynchronous trading bot implementation."""
from __future__ import annotations
import datetime as dt
from typing import Optional

from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiMessages_pb2 import *            # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402

from twisted.internet import reactor  # type: ignore

from .settings import (
    CLIENT_ID,
    CLIENT_SECRET,
)
from .helpers import insert_deal


class SimpleBot:
    """Encapsulates the trading cycle (open→hold→close→reconcile)."""

    def __init__(
        self,
        client: Client,
        access_token: str,
        account_id: int,
        symbol_id: int,
        side: str,
        volume: int,
        hold: int,
    ) -> None:
        self.client = client
        self.access_token = access_token
        self.account_id = account_id
        self.symbol_id = symbol_id
        self.trade_side = side.upper()
        self.volume = volume * 100  # micro‑lots → base units
        self.hold = hold
        self.open_position_id: Optional[int] = None

        # Register callbacks
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)

    # ------------------------------------------------------------------
    # Life‑cycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Kick‑off the bot – blocks the main thread until finished."""
        self.client.startService()
        reactor.run()

    # ------------------------------------------------------------------
    # Low‑level cTrader event handlers
    # ------------------------------------------------------------------
    def _on_connected(self, _):
        print("[+] Connected. Authenticating app…")
        req = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        self.client.send(req)

    def _on_disconnected(self, _, reason):
        print("[-] Disconnected:", reason)
        if reactor.running:
            reactor.stop()

    def _on_message(self, _, msg):
        pt = msg.payloadType
        if pt in {
            ProtoHeartbeatEvent().payloadType,
        }:
            return  # Ignore low‑level heartbeats

        # Debug helper
        print(f"[debug] Incoming payloadType = {pt}")

        # Define constants once
        if pt == ProtoOAApplicationAuthRes().payloadType:
            self._after_app_auth()
        elif pt == ProtoOAAccountAuthRes().payloadType:
            self._after_account_auth()
        elif pt == ProtoOAPositionUpdateEvent().payloadType:
            self._on_position_update(Protobuf.extract(msg))
        elif pt == ProtoOAExecutionEvent().payloadType:
            self._handle_execution(Protobuf.extract(msg))
        elif pt == ProtoOAReconcileRes().payloadType:
            print("[✓] Reconcile complete. Exiting…")
            reactor.stop()
        elif pt in {
            ProtoOAOrderErrorEvent().payloadType,
            ProtoOAErrorRes().payloadType
        }:
            self._on_error(Protobuf.extract(msg))
        else:
            from google.protobuf.json_format import MessageToDict
            print(MessageToDict(Protobuf.extract(msg)))



    # High‑level message handlers ------------------------------------------------
    def _after_app_auth(self):
        print("[✓] App authenticated. Authorizing account…")
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=self.account_id, accessToken=self.access_token
        )
        self.client.send(req)

    def _after_account_auth(self):
        print("[✓] Account authorized. Sending market order…")
        self._send_market_order()

    def _on_position_update(self, update):
        for pos in update.position:
            print(
                f"[PnL] Pos {pos.positionId} | Sym {pos.symbolId} | Unrealized {pos.unrealisedNetProfit:.2f}"
            )

    def _on_error(self, err):
        from google.protobuf.json_format import MessageToDict

        print("[✖] Server error:", MessageToDict(err))
        if reactor.running:
            reactor.stop()

    # Trading helpers -----------------------------------------------------------
    def _send_market_order(self):
        req = ProtoOANewOrderReq(
            ctidTraderAccountId=self.account_id,
            symbolId=self.symbol_id,
            orderType=ProtoOAOrderType.MARKET,
            tradeSide=ProtoOATradeSide.Value(self.trade_side),
            volume=self.volume,
        )
        self.client.send(req)

    def _close_position(self):
        if self.open_position_id is None:
            print("[!] No open position to close.")
            return
        print("[→] Closing position…")
        req = ProtoOAClosePositionReq(
            ctidTraderAccountId=self.account_id,
            positionId=self.open_position_id,
            volume=self.volume,
        )
        d = self.client.send(req)
        d.addErrback(lambda f: print("[✖] Close failed:", f))

    def _reconcile(self):
        self.client.send(ProtoOAReconcileReq(ctidTraderAccountId=self.account_id))

    # Execution event processing ------------------------------------------------
    def _handle_execution(self, ev):
        print("[✓] Execution Event:")
        print(f"  executionType: {ev.executionType}")
        deal, order, pos = ev.deal, ev.order, ev.position

        data = {
            "deal_id": deal.dealId,
            "position_id": pos.positionId,
            "order_id": order.orderId,
            "side": order.tradeData.tradeSide,
            "volume": deal.volume,
            "price": deal.executionPrice,
            "commission": deal.commission,
            "swap": pos.swap,
            "used_margin": pos.usedMargin,
            "execution_type": ev.executionType,
            "timestamp": dt.datetime.utcnow(),
        }
        # Fire‑and‑forget DB insert – don't block Twisted reactor
        from twisted.internet.defer import ensureDeferred

        ensureDeferred(insert_deal(data))

        if ev.executionType == ProtoOAExecutionType.ORDER_FILLED:
            if self.open_position_id is None:  # first fill (open)
                self.open_position_id = pos.positionId
                print(f"[→] Position opened {self.open_position_id}. Hold {self.hold}s…")
                reactor.callLater(self.hold, self._close_position)
            else:  # second fill (close)
                print(f"[✓] Position {self.open_position_id} closed.")
                self._reconcile()