"""
Shared DB connection helper for the anomaly engine, scoring modules, and the
Streamlit app.

Connection resolution order (first match wins):
  1. Streamlit secrets (`st.secrets["DATABASE_URL"]`) — used when deployed on
     Streamlit Community Cloud, where secrets are configured in the app's
     dashboard, never committed to git. Only checked if `streamlit` is both
     importable AND actually running inside a Streamlit session (importing
     streamlit standalone does not mean st.secrets is populated) — everything
     here is wrapped so the CLI pipeline scripts, which never run inside
     Streamlit, are unaffected.
  2. `DATABASE_URL` env var — a single connection string, the format most
     managed Postgres providers (Neon, Supabase, Render) hand you directly.
  3. Discrete `POSTGRES_*` env vars from `.env` — the original local-dev path,
     unchanged, so `docker compose up -d` + `.env` keeps working exactly as
     before this file changed.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

_engine = None


def _url_from_streamlit_secrets():
    try:
        import streamlit as st
    except ImportError:
        return None
    try:
        # st.secrets raises if no secrets.toml exists AND no cloud secrets are
        # configured — that's expected for local `streamlit run` without a
        # secrets file, so treat it as "not available" rather than an error.
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        return None
    return None


def _build_url() -> str:
    from_secrets = _url_from_streamlit_secrets()
    if from_secrets:
        return from_secrets

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # normalize the common "postgres://" / "postgresql://" scheme (what
        # most providers give you) to the psycopg2 driver SQLAlchemy needs
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return database_url

    return (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'sellerpulse')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'change_me')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', 5433)}/"
        f"{os.getenv('POSTGRES_DB', 'sellerpulse')}"
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_build_url(), pool_pre_ping=True)
    return _engine
