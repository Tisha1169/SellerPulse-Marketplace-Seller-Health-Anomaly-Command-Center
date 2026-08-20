"""Shared DB connection helper for the anomaly engine and scoring modules."""
import os

from sqlalchemy import create_engine

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = (
            f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'sellerpulse')}:"
            f"{os.getenv('POSTGRES_PASSWORD', 'change_me')}@"
            f"{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', 5433)}/"
            f"{os.getenv('POSTGRES_DB', 'sellerpulse')}"
        )
        _engine = create_engine(url)
    return _engine
