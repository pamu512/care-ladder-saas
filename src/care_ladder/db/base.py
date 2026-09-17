"""Engine helpers for the SaaS Postgres store.

Tests use sqlite in-memory; production passes a postgres+psycopg URL.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def create_engine_from_url(url: str):
    if url.startswith("sqlite") and ":memory:" in url:
        # single shared connection so all sessions see the same in-memory schema
        return create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
