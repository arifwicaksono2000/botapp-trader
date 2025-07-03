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
            lot_size=lot_size,
            status='running'
        )
        s.add(new_trade_detail)
        s.commit()
        s.refresh(new_trade_detail)
        print(f"Successfully created new TradeDetail: ID={new_trade_detail.id}, PosID={position_id}")
        return new_trade_detail

def update_trade_on_close(position_id: int, exit_price: float, commission: float, swap: float):
    """
    Finds the TradeDetail by position_id and updates it with closing data.
    If all details for a trade are closed, it updates the parent Trade as well.
    This version includes checks to prevent double-updates and has a more accurate P/L calculation.
    """
    with SessionSync() as s:
        # 1. Find the specific TradeDetail
        trade_detail = s.query(TradeDetail).filter_by(position_id=position_id).first()
        if not trade_detail:
            print(f"[DB ERROR] Could not find TradeDetail for positionId: {position_id}")
            return

        # --- FIX 1: Prevent double-updates ---
        # If this detail has already been closed, do nothing.
        if trade_detail.status == 'closed' and trade_detail.closed_at is not None:
            print(f"[DB INFO] TradeDetail for position {position_id} is already closed. No action taken.")
            return
        
        # Mark the detail as closed
        trade_detail.exit_price = exit_price
        trade_detail.closed_at = dt.datetime.now(dt.timezone.utc)
        trade_detail.status = 'closed' # Explicitly set the status
        
        # Calculate pips
        pips = (exit_price - float(trade_detail.entry_price)) * 10000
        if trade_detail.position_type == 'short':
            pips = -pips
        trade_detail.pips = pips
        
        print(f"[DB UPDATE] Closed TradeDetail {trade_detail.id} for Pos {position_id}. Pips: {pips:.2f}")

        # 2. Check if the parent Trade is now complete
        parent_trade_id = trade_detail.trade_id
        # We need to re-query the details within the same session to get the most up-to-date state
        sibling_details = s.query(TradeDetail).filter_by(trade_id=parent_trade_id).all()
        
        all_closed = all(detail.status == 'closed' for detail in sibling_details)

        if all_closed:
            parent_trade = s.query(Trades).get(parent_trade_id)
            print(f"[DB UPDATE] All details for Trade {parent_trade.id} are closed. Finalizing parent trade.")
            
            # --- FIX 2: More Accurate P/L Calculation ---
            # Now includes commission and swap fees.
            total_pnl = 0
            for detail in sibling_details:
                lot_size_units = float(detail.lot_size) * 100000
                price_pnl = (float(detail.exit_price) - float(detail.entry_price)) * lot_size_units
                if detail.position_type == 'short':
                    price_pnl = -price_pnl
                total_pnl += price_pnl

            # The final P/L should account for costs. Note: commission and swap from cTrader are usually negative.
            # We add them directly. The final commission/swap will be the sum from the last deal event.
            final_pnl = total_pnl + commission + swap

            parent_trade.ending_balance = float(parent_trade.starting_balance) + final_pnl
            parent_trade.status = 'successful' if final_pnl >= 0 else 'liquidated'
            parent_trade.closed_at = dt.datetime.now(dt.timezone.utc)

        s.commit()

def fetch_account_balance(account_pk: int) -> float:
    """Fetches the current balance for a given subaccount primary key."""
    with SessionSync() as s:
        subaccount = s.query(Subaccount).get(account_pk)
        if not subaccount:
            raise RuntimeError(f"Subaccount with pk {account_pk} not found.")
        return float(subaccount.balance)

def update_trade_detail_on_close(position_id: int, exit_price: float, commission: float, swap: float, final_status: str):
    """Updates a single TradeDetail row when a position is closed."""
    with SessionSync() as s:
        trade_detail = s.query(TradeDetail).filter_by(position_id=position_id).first()
        if not trade_detail or trade_detail.status != 'running':
            return # Already handled

        trade_detail.exit_price = exit_price
        trade_detail.closed_at = dt.datetime.now(dt.timezone.utc)
        trade_detail.status = final_status # 'successful' or 'liquidated'
        
        # Calculate pips
        pips = (exit_price - float(trade_detail.entry_price)) * 10000
        if trade_detail.position_type == 'short':
            pips = -pips
        trade_detail.pips = pips
        
        print(f"[DB UPDATE] Set TradeDetail for Pos {position_id} to '{final_status}'.")
        s.commit()

def update_parent_trade_status(trade_id: int, final_status: str):
    """Updates the parent Trade row to a final status."""
    with SessionSync() as s:
        parent_trade = s.query(Trades).get(trade_id)
        if parent_trade and parent_trade.status == 'running':
            parent_trade.status = final_status
            parent_trade.closed_at = dt.datetime.now(dt.timezone.utc)
            print(f"[DB UPDATE] Set parent Trade {trade_id} to '{final_status}'.")
            s.commit()
