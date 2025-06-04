"""Utility coroutines shared across modules."""
from __future__ import annotations

from sqlalchemy import select, desc

from .database import Session
from .models import TokenDB, Subaccount


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
    
# async def insert_deal(data: dict):
#     """Insert deal log – silently ignore unknown keys to keep compatibility."""
#     valid_cols = {c.name for c in DealLog.__table__.columns}  # type: ignore[attr-defined]
#     filtered = {k: v for k, v in data.items() if k in valid_cols}

#     async with Session() as s:
#         async with s.begin():
#             s.add(DealLog(**filtered))