#!/usr/bin/env python3
"""
main.py
================================
*   Robust asynchronous cTrader bot
*   Automatic token refresh & reconnect
*   Safe DB insert that filters unknown columns
*   Works on macOS / Linux / Windows

Usage:
  python main.py --side buy --volume 1000 --hold 60

"""

import argparse
import asyncio
import os
import sys
import datetime as dt
from functools import partial
from typing import Optional
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

# -----------------------------------------------------------------------------
# Twisted↔︎asyncio reactor bridging (platform‑safe)
# -----------------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from twisted.internet import asyncioreactor  # noqa: E402
asyncioreactor.install(loop)                  # must be before importing reactor
from twisted.internet import reactor          # noqa: E402

# -----------------------------------------------------------------------------
# cTrader Open‑API imports
# -----------------------------------------------------------------------------
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints  # noqa: E402
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiMessages_pb2 import *            # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402

# -----------------------------------------------------------------------------
# SQLAlchemy async setup
# -----------------------------------------------------------------------------
from sqlalchemy import (  # noqa: E402
    Column, DateTime, Float, Integer, BigInteger, Boolean, Text, MetaData, desc,
    select
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession  # noqa: E402
from sqlalchemy.orm import declarative_base, sessionmaker            # noqa: E402

load_dotenv()

Base = declarative_base(metadata=MetaData())

# -----------------------------------------------------------------------------
# Database models
# -----------------------------------------------------------------------------

class TokenDB(Base):
    __tablename__ = "botcore_token"
    id = Column(Integer, primary_key=True)
    access_token = Column(Text)
    refresh_token = Column(Text)
    is_used = Column(Boolean)
    expired_at = Column(DateTime)
    created_at = Column(DateTime)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT", 0))
SYMBOL_ID = int(os.getenv("CTRADER_SYMBOL_ID", 1))  # EUR/USD default

# -----------------------------------------------------------------------------
# Helper utilities
# -----------------------------------------------------------------------------
async def fetch_access_token(session_maker: sessionmaker) -> str:
    """Fetch the latest active access‑token from DB."""
    async with session_maker() as s:
        result = await s.execute(
            select(TokenDB.access_token)
            .where(TokenDB.is_used.is_(True))
            .order_by(desc(TokenDB.created_at))
            .limit(1)
        )
        row = result.first()
        if not row:
            raise RuntimeError("No valid access token found in DB")
        return row[0]

async def insert_deal(session_maker: sessionmaker, data: dict):
    """Safely insert deal log – unknown keys are ignored."""
    valid_cols = {c.name for c in DealLog.__table__.columns}
    filtered = {k: v for k, v in data.items() if k in valid_cols}
    async with session_maker() as s:
        async with s.begin():
            s.add(DealLog(**filtered))

# -----------------------------------------------------------------------------
# Bot implementation
# -----------------------------------------------------------------------------
class SimpleBot:
    def __init__(self, client: Client, sessionmaker: sessionmaker, access_token: str,
                 account_id: int, symbol_id: int, side: str, volume: int, hold: int):
        self.client = client
        self.sessionmaker = sessionmaker
        self.access_token = access_token
        self.account_id = account_id
        self.symbol_id = symbol_id
        self.trade_side = side.upper()
        self.volume = volume * 100  # convert micro‑lots → base units
        self.hold = hold
        self.open_position_id: Optional[int] = None

        # register callbacks
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)

    @classmethod
    def client_factory(cls, access_token, Session, args):
        client = Client(HOST, PORT, TcpProtocol)
        return cls(
            client=client,
            sessionmaker=Session,
            access_token=access_token,
            account_id=int(os.getenv("CTRADER_ACCOUNT")),
            symbol_id=int(os.getenv("CTRADER_SYMBOL_ID")),
            side=args.side,
            volume=args.volume,
            hold=args.hold,
            # open_position_id=None
        )

    # ------------------------------------------------------------------
    # Service life‑cycle
    # ------------------------------------------------------------------
    def start(self):
        self.client.startService()
        reactor.run()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_connected(self, _):
        print("[+] Connected. Authenticating app…")
        req = ProtoOAApplicationAuthReq()
        req.clientId = CLIENT_ID
        req.clientSecret = CLIENT_SECRET
        self.client.send(req)

    def _on_disconnected(self, _, reason):
        print("[-] Disconnected:", reason)
        if reactor.running:
            reactor.stop()

    def _on_message(self, _, msg):
        pt = msg.payloadType
        if pt in {ProtoHeartbeatEvent().payloadType,
                  ProtoOASubscribeSpotsRes().payloadType}:
            return  # ignore heartbeats & subscription acks

        print(f"[debug] Incoming payloadType = {pt}")

        if pt == ProtoOAApplicationAuthRes().payloadType:
            print("[✓] App authenticated. Authorizing account…")
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = self.account_id
            req.accessToken = self.access_token
            self.client.send(req)
            return

        if pt == ProtoOAAccountAuthRes().payloadType:
            print("[✓] Account authorized. Sending market order…")
            self._send_market_order()
            return
        
        if pt == ProtoOAPositionUpdateEvent().payloadType:
            position_update = Protobuf.extract(msg)
            for pos in position_update.position:
                # Log the real-time unrealized PnL
                print(f"[PnL Update] Symbol {pos.symbolId} | Position ID {pos.positionId} | Unrealized PnL: {pos.unrealisedNetProfit:.2f}")


        if pt == ProtoOAExecutionEvent().payloadType:
            self._handle_execution(Protobuf.extract(msg))
            return

        if pt == ProtoOAReconcileRes().payloadType:
            print("[✓] Reconcile complete. Exiting…")
            reactor.stop()
            return

        if pt in {ProtoOAOrderErrorEvent().payloadType, ProtoOAErrorRes().payloadType}:
            err = Protobuf.extract(msg)
            print("[✖] Server error: ", MessageToDict(err))
            if reactor.running:
                reactor.stop()
            return

        # default: print as dict for debugging other payloads
        print(MessageToDict(Protobuf.extract(msg)))

    # ------------------------------------------------------------------
    # Execution handling
    # ------------------------------------------------------------------
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
        # asyncio.create_task(insert_deal(self.sessionmaker, data))

        if ev.executionType == ProtoOAExecutionType.ORDER_FILLED:
            if self.open_position_id is None:  # first fill (open)
                self.open_position_id = pos.positionId
                print(f"[→] Position opened {self.open_position_id}. Will hold {self.hold}s…")
                reactor.callLater(self.hold, self._close_position)
            else:  # second fill (close)
                print(f"[✓] Position {self.open_position_id} closed.")
                self._reconcile()

    # ------------------------------------------------------------------
    # Helper API requests
    # ------------------------------------------------------------------
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
        # self.notify_web_status_update({"state": "idle", "msg": "Trade cycle complete"})
        self.client.send(ProtoOAReconcileReq(ctidTraderAccountId=self.account_id))
    
    def notify_web_status_update(data: dict):
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "bot_updates",
            {
                "type": "send.bot.status",
                "data": data,
            }
        )

# -----------------------------------------------------------------------------
# Entry‑point
# -----------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description="Async cTrader hedging bot")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--volume", type=int, default=1000, help="Volume in micro‑lots (1000 = 0.01 lot)")
    p.add_argument("--hold", type=int, default=60, help="Seconds to hold before closing")
    return p


def main():
    args = build_parser().parse_args()

    # DB setup
    db_url = os.getenv("MYSQL_URL")
    engine = create_async_engine(db_url, echo=False, future=True)
    Session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def bootstrap():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return await fetch_access_token(Session)

    token = loop.run_until_complete(bootstrap())

    client = Client(HOST, PORT, TcpProtocol)
    bot = SimpleBot(client, Session, token, ACCOUNT_ID, SYMBOL_ID,
                    args.side, args.volume, args.hold)
    bot.start()

if __name__ == "__main__":
    main()
