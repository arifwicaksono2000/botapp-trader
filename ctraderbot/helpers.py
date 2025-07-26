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
from decimal import Decimal
from sqlalchemy import and_

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

def update_parent_trade_status(trade_id: int, final_status: str, resulted_balance: float):
    """
    Updates the parent Trade row to a final status, calculates the final
    balance, determines the achieved level, and updates the parent Segment.
    """
    with SessionSync() as s:
        # 1. Get the parent trade
        parent_trade = s.query(Trades).get(trade_id)
        if not parent_trade or parent_trade.status != 'running':
            return # Exit if trade is not found or already closed

        # ... (PnL and ending_balance calculation logic remains the same)
        # sibling_details = s.query(TradeDetail).filter_by(trade_id=parent_trade.id).all()
        # if not sibling_details:
        #     print(f"[DB WARN] No trade details found for Trade {trade_id}. Cannot calculate ending balance.")
        #     return

        # total_pnl = Decimal('0.0')
        # for detail in sibling_details:
        #     if detail.exit_price is None or detail.entry_price is None:
        #         continue

        #     lot_size_in_units = detail.lot_size * 100000
        #     price_difference = detail.exit_price - detail.entry_price

        #     if detail.position_type == 'short':
        #         price_difference = -price_difference

        #     position_pnl = price_difference * lot_size_in_units
        #     total_pnl += position_pnl

        # 4. Update the parent trade object
        parent_trade.status = final_status
        parent_trade.closed_at = dt.datetime.now(dt.timezone.utc)
        parent_trade.ending_balance = resulted_balance
        # parent_trade.ending_balance = parent_trade.starting_balance + total_pnl

        # 5. Update achieved_level_id based on the outcome
        if final_status == 'successful':
            # ---- START: MODIFIED MILESTONE LOGIC ----
            # Find the new milestone based on where the ending_balance falls
            new_milestone = s.query(Milestone).filter(
                and_(
                    Milestone.starting_balance <= parent_trade.ending_balance,
                    Milestone.ending_balance > parent_trade.ending_balance
                )
            ).first()

            if new_milestone:
                parent_trade.achieved_level_id = new_milestone.id
                print(f"[DB UPDATE] Trade successful. New achieved level is {new_milestone.id}.")
            else:
                # If no milestone fits, it might be the last one or an edge case.
                # Default to the current level.
                parent_trade.achieved_level_id = parent_trade.current_level_id
                print("[DB UPDATE] Trade successful but no new milestone found. Reached end of levels.")
            # ---- END: MODIFIED MILESTONE LOGIC ----

        else: # 'liquidated' or other failure status
            parent_trade.achieved_level_id = parent_trade.current_level_id

        print(f"[DB UPDATE] Set parent Trade {trade_id} to '{final_status}' with ending balance: {parent_trade.ending_balance:.2f}")

        # ---- START: NEW SEGMENT UPDATE LOGIC ----

        # 6. Get the parent segment to update its status
        parent_segment = s.query(Segments).get(parent_trade.segment_id)
        if not parent_segment:
            return

        # 7. Handle Segment Liquidation
        if final_status == 'liquidated':
            parent_segment.status = 'liquidated'
            parent_segment.closed_at = dt.datetime.now(dt.timezone.utc)
            print(f"[DB UPDATE] Segment {parent_segment.id} has been liquidated.")

            # If the liquidated segment was the pivot, find and assign a new one
            if parent_segment.is_pivot:
                parent_segment.is_pivot = False
                print(f"[DB UPDATE] Pivot Segment {parent_segment.id} liquidated. Finding new pivot...")

                # Find the next running segment, ordered by creation time
                next_pivot_segment = s.query(Segments).filter(
                    Segments.subaccount_id == parent_segment.subaccount_id,
                    Segments.status == 'running'
                ).order_by(Segments.opened_at.asc()).first()

                if next_pivot_segment:
                    next_pivot_segment.is_pivot = True
                    print(f"[DB UPDATE] Segment {next_pivot_segment.id} is the new pivot.")
                else:
                    print("[DB WARN] No other running segments available to become the new pivot.")

        # 8. Handle Segment Success (Reaching Ending Level)
        # Only pivot segment can have unlimited level, because it always going to give
        else: # Check for success only if not liquidated
            ending_level_row = s.query(Constant).filter_by(variable='ending_level', is_active=True).first()
            if ending_level_row:
                ending_level_value = Decimal(ending_level_row.value)
                # Check if the segment's new total balance meets the ending level
                if parent_trade.ending_balance >= ending_level_value:
                    parent_segment.status = 'successful'
                    parent_segment.closed_at = dt.datetime.now(dt.timezone.utc)
                    print(f"[DB UPDATE] Segment {parent_segment.id} has reached the ending level and is now successful.")
            else:
                print("[DB WARN] 'ending_level' constant not found. Cannot check for segment success.")

        # ---- END: NEW SEGMENT UPDATE LOGIC ----
        
        s.commit()

def update_account_balance_in_db(account_pk: int, new_balance: float):
    """
    Updates the balance for a specific subaccount in the database.
    """
    with SessionSync() as s:
        subaccount = s.query(Subaccount).filter_by(id=account_pk).first()
        if subaccount:
            print(f"[DB UPDATE] Syncing account {account_pk} balance to: {new_balance:.2f}")
            subaccount.balance = new_balance
            s.commit()
        else:
            print(f"[DB WARN] Could not find subaccount with pk {account_pk} to update balance.")
