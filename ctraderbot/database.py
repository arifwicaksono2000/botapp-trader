"""SQLAlchemy async engine, Session factory & declarative base."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import MetaData, create_engine

from .settings import MYSQL_URL, MYSQL_SYNC_URL

engine = create_async_engine(MYSQL_URL, echo=False, future=True)
Session: sessionmaker[AsyncSession] = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

SyncEngine = create_engine(MYSQL_SYNC_URL, echo=False, future=True)
SessionSync = sessionmaker(bind=SyncEngine)

Base = declarative_base(metadata=MetaData())