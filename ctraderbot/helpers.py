"""Utility coroutines shared across modules."""
from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.orm import Session as SyncSession
import uuid
from .database import Session, SessionSync
from .models import *
from datetime import timezone


async def fetch_access_token() -> str:
    """Return the latest *active* access‑token from DB or raise."""
    async with Session() as s:
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

# --- Function to create and save a new Segment ---
def create_new_segment(
    subaccount_id: int,
    milestone_id: int,
    total_balance: float,
    pair: str,
    total_positions: int = 0 # Assuming new segments start with 0 positions
):
    """
    Creates and saves a new Segment entry in the database.
    """
    new_segment_uuid = str(uuid.uuid4()) # Generate UUID as string for SQLAlchemy
    new_segment = Segment(
        uuid=new_segment_uuid,
        subaccount_id=subaccount_id,
        milestone_id=milestone_id,
        total_positions=total_positions,
        total_balance=total_balance,
        pair=pair,
        opened_at=dt.datetime.now(timezone.utc), # Use UTC time for consistency
        closed_at=None, # A new segment is initially open
        status='running'
    )

    with SessionSync() as s:
        s.add(new_segment)
        s.commit()
        s.refresh(new_segment) # Refresh to get the ID if needed
        print(f"Successfully created new Segment: ID={new_segment.id}, UUID={new_segment.uuid}, Opened At={new_segment.opened_at}")
        return new_segment

def should_open_new_segment(latest_segment_opened_at: dt.datetime) -> bool:
    """
    Checks if the current UTC time is past 7 PM UTC of the day after
    latest_segment_opened_at.

    Args:
        latest_segment_opened_at: The datetime object of the last segment's opening.
                                  Assumed to be in UTC (naive or timezone-aware).

    Returns:
        True if a new segment should be opened, False otherwise.
    """
    now_utc = dt.datetime.now(timezone.utc) # <--- Use timezone.utc here

    # Calculate the date for "tomorrow" relative to latest_segment_opened_at
    day_after_opened_at = latest_segment_opened_at + dt.timedelta(days=1)

    # Set the time to 19:00:00 (7 PM UTC) on that "tomorrow" date
    # .replace() creates a new datetime object with the specified time parts
    comparator_timestamp = day_after_opened_at.replace(
        hour=19, minute=0, second=0, microsecond=0
    )

    print(f"Current UTC time:        {now_utc}")
    print(f"Latest Segment Opened At: {latest_segment_opened_at}")
    print(f"Comparator Timestamp:    {comparator_timestamp}")

    return now_utc >= comparator_timestamp

# --- Function to fetch the current active Milestone (similar to your original snippet) ---
# This function assumes 'current_balance' is available in the scope where it's called.
# You might need to adjust it to take `current_balance` as an argument or fetch it from the bot state.
def fetch_current_milestone(current_balance: float):
    """
    Fetches the active Milestone based on the current balance.
    """
    with SessionSync() as s:
        # Assuming Milestone has appropriate fields for balance ranges
        active_milestone = s.execute(
            select(Milestone)
            .where(
                Milestone.starting_balance <= current_balance,
                Milestone.ending_balance >= current_balance,
            )
            .limit(1) # Assuming only one milestone is active at a time for a given balance
        ).scalars().first()
        return active_milestone

# --- Function to fetch the latest Segment (from previous answer) ---
def fetch_latest_segment(subaccount_id: int):
    """
    Selects the latest Segment row for a given subaccount_id,
    ordered by opened_at in descending order.
    """
    with SessionSync() as s:
        latest_segment = s.execute(
            select(Segment)
            .where(
                Segment.subaccount_id == subaccount_id
            )
            .order_by(
                desc(Segment.opened_at)
            )
            .limit(1)
        ).scalars().first()

        return latest_segment

# --- Integrated Logic Example ---
# This function would be part of your bot's main loop or a periodic check.
# It assumes 'bot' object has access to `account_id`, `current_balance`, `symbol_id`
def manage_segments(bot):
    # 1. Fetch the latest segment for the current subaccount
    latest_segment = fetch_latest_segment(bot.account_id)

    if latest_segment is None:
        # No segments exist for this subaccount, so create the first one
        print("No existing segments found. Creating the initial segment.")
        # You'll need to decide how to get the initial milestone_id, total_balance, pair
        # For simplicity, let's assume current_balance and symbol_id are available from 'bot'
        current_milestone = fetch_current_milestone(bot.current_balance) # Pass actual current balance
        if current_milestone:
            new_segment = create_new_segment(
                subaccount_id=bot.account_id,
                milestone_id=current_milestone.id,
                total_balance=bot.current_balance, # Use actual current balance from bot
                pair=bot.symbol_id # Use actual symbol pair from bot (e.g., 'EURUSD')
            )
            # You might want to store this new_segment ID in your bot's state
            bot.current_segment_id = new_segment.id
        else:
            print("Error: Could not find an active milestone to link the initial segment.")
            # Handle this error case: perhaps log, or create segment without milestone_id temporarily
        return

    # 2. Check if a new segment should be opened based on the time condition
    if should_open_new_segment(latest_segment.opened_at):
        print("Time condition met! Opening a new segment.")
        # Optionally, close the previous segment if it's not already closed
        if latest_segment.closed_at is None:
            with SessionSync() as s:
                s.add(latest_segment) # Re-add to session to make it 'dirty'
                latest_segment.closed_at = dt.datetime.now(timezone.utc)
                s.commit()
                print(f"Closed previous Segment: ID={latest_segment.id}")

        # Fetch the current active milestone for the new segment
        current_milestone = fetch_current_milestone(bot.current_balance) # Pass actual current balance
        if current_milestone:
            new_segment = create_new_segment(
                subaccount_id=bot.account_id,
                milestone_id=current_milestone.id,
                total_balance=bot.current_balance, # Use actual current balance from bot
                pair=bot.symbol_id # Use actual symbol pair from bot (e.g., 'EURUSD')
            )
            # You might want to store this new_segment ID in your bot's state
            bot.current_segment_id = new_segment.id
        else:
            print("Error: Could not find an active milestone to link the new segment.")
            # Handle this error case
    else:
        print("Time condition not met. Continuing with the current segment.")
        # Ensure the bot's current_segment_id is set to the latest one found
        bot.current_segment_id = latest_segment.id