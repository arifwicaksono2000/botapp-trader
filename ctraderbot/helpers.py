# file: ctraderbot/helpers.py
"""Utility coroutines shared across modules."""
from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.orm import Session as SyncSession
import uuid
from .database import Session, SessionSync
from .models import * # Imports all the new model names
from datetime import timezone
import datetime as dt

async def fetch_access_token() -> str:
    """Return the latest *active* access‑token from DB or raise."""
    async with Session() as s:
        result = await s.execute(
            select(Token.access_token)
            .where(Token.is_used.is_(True))
            .order_by(desc(Token.created_at))
            .limit(1)
        )
        row = result.first()
        if not row:
            raise RuntimeError("No valid access token found in DB")
        return row[0]

async def fetch_main_account() -> int:
    """Return the *main* account from DB or raise."""
    async with Session() as s:
        result = await s.execute(
            select(Subaccount.account_id)
            .where(Subaccount.is_default.is_(True))
            .limit(1)
        )
        row = result.first()
        if not row:
            raise RuntimeError("No valid account found in DB")
        return int(row[0])

def fetch_milestone(account_id: int):
    with SessionSync() as s:
        row = s.execute(
            select(Subaccount.balance)
            .where(Subaccount.account_id == str(account_id))
            .limit(1)
        ).first()
        if not row:
            raise RuntimeError("Account not found in DB")
        current_balance = float(row[0])

        milestone = s.execute(
            select(Milestone)
            .where(
                Milestone.starting_balance <= current_balance,
                Milestone.ending_balance >= current_balance,
            )
            .limit(1)
        ).scalars().first()

        return current_balance, milestone
    
async def fetch_main_account() -> tuple[int, int]:
    """Return the primary key and cTrader ID of the *main* account or raise."""
    async with Session() as s:
        result = await s.execute(
            select(Subaccount.id, Subaccount.account_id)
            .where(Subaccount.is_default.is_(True))
            .limit(1)
        )
        row = result.first()
        if not row:
            raise RuntimeError("No valid default account found in DB")
        # row[0] is the primary key (id), row[1] is the cTrader account_id
        return row[0], int(row[1])

def create_new_segment(
    subaccount_id: int,
    milestone_id: int, # milestone_id is no longer on the model, but we keep it for now
    total_balance: float,
    pair: str,
    total_positions: int = 0,
    is_pivot: bool = False
) -> Segments:
    """
    Creates and saves a new Segments entry in the database.
    """
    new_segment_uuid = str(uuid.uuid4())
    new_segment = Segments(
        uuid=new_segment_uuid,
        subaccount_id=subaccount_id,
        total_positions=total_positions,
        total_balance=total_balance,
        pair=pair,
        opened_at=dt.datetime.now(timezone.utc),
        closed_at=None,
        status='running',
        is_pivot=is_pivot
    )

    with SessionSync() as s:
        s.add(new_segment)
        s.commit()
        s.refresh(new_segment)
        print(f"Successfully created new Segment: ID={new_segment.id}, UUID={new_segment.uuid}")
        return new_segment

def fetch_running_pivot_segment(subaccount_id: int) -> Segments | None:
    """
    Selects the latest Segments row for a given subaccount_id.
    """
    with SessionSync() as s:
        latest_segment = s.execute(
            select(Segments)
            .where(Segments.subaccount_id == subaccount_id)
            .where(Segments.is_pivot == True)
            .where(Segments.status == 'running')
            .order_by(desc(Segments.opened_at))
            .limit(1)
        ).scalars().first()
        return latest_segment

def create_trade(segment_id: int, milestone_id: int, current_balance: float) -> Trades:
    """
    Creates and saves a new Trades entry in the database.
    """
    new_trade_uuid = str(uuid.uuid4())
    with SessionSync() as s:
        milestone = s.query(Milestone).filter_by(id=milestone_id).one()
        new_trade = Trades(
            uuid=new_trade_uuid,
            segment_id=segment_id,
            curr_active="B",  # 'Both'
            current_level_id=milestone_id,
            starting_balance=current_balance,
            profit_goal=milestone.profit_goal,
            status='running'
        )
        s.add(new_trade)
        s.commit()
        s.refresh(new_trade)
        print(f"Successfully created new Trade: ID={new_trade.id}, UUID={new_trade.uuid}")
        return new_trade

def create_trade_detail(trade_id: int, segment_id: int, position_id: int, side: str, lot_size: float, entry_price: float) -> TradeDetail:
    """
    Creates and saves a new TradeDetail entry in the database.
    """
    new_detail_uuid = str(uuid.uuid4())
    position_type = 'long' if side == "BUY" else 'short'
    
    with SessionSync() as s:
        new_trade_detail = TradeDetail(
            uuid=new_detail_uuid,
            trade_id=trade_id,
            segment_id=segment_id,
            position_id=position_id,
            position_type=position_type,
            entry_price=entry_price,
            lot_size=lot_size
        )
        s.add(new_trade_detail)
        s.commit()
        s.refresh(new_trade_detail)
        print(f"Successfully created new TradeDetail: ID={new_trade_detail.id}, PosID={position_id}")
        return new_trade_detail