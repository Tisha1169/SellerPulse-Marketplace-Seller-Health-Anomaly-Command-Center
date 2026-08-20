"""
Integration checks against the live database — verifies the pipeline's
downstream tables are internally consistent, not just that each stage ran
without throwing. Skipped if no database is reachable.
"""
import pandas as pd
import pytest
from sqlalchemy.exc import OperationalError

from anomaly_engine.db import get_engine


def _db_available() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable — start with `docker compose up -d`")


@pytest.fixture(scope="module")
def engine():
    return get_engine()


def test_every_ensemble_flag_traces_to_at_least_two_methods(engine):
    """A written Ensemble flag's reason_code should always list >=2 methods —
    this is the invariant the whole precision story in evaluate.py depends on."""
    df = pd.read_sql(
        "SELECT reason_code FROM core.fact_anomaly_flags WHERE method = 'Ensemble'", engine
    )
    if df.empty:
        pytest.skip("No Ensemble flags in database — run anomaly_engine.ensemble first")
    method_names = {"ZScore", "IQR", "CUSUM", "IsolationForest"}
    n_methods = df["reason_code"].apply(lambda rc: len([p for p in rc.split("_") if p in method_names]))
    assert (n_methods >= 2).all()


def test_every_ticket_has_a_valid_primary_flag(engine):
    df = pd.read_sql(
        """
        SELECT t.case_id FROM core.investigation_tickets t
        LEFT JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
        WHERE f.flag_id IS NULL
        """,
        engine,
    )
    assert df.empty, f"{len(df)} tickets reference a nonexistent flag_id"


def test_only_high_and_critical_flags_have_tickets(engine):
    df = pd.read_sql(
        "SELECT DISTINCT severity FROM core.investigation_tickets", engine
    )
    if df.empty:
        pytest.skip("No tickets in database")
    assert set(df["severity"]) <= {"High", "Critical"}


def test_health_scores_bounded_0_100(engine):
    df = pd.read_sql(
        "SELECT min(health_score) AS lo, max(health_score) AS hi FROM core.seller_health_score", engine
    )
    if df["lo"].iloc[0] is None:
        pytest.skip("No health scores in database")
    assert df["lo"].iloc[0] >= 0 and df["hi"].iloc[0] <= 100


def test_sla_deadline_after_detected_date(engine):
    df = pd.read_sql(
        "SELECT count(*) AS n FROM core.investigation_tickets WHERE sla_deadline <= detected_date::timestamp",
        engine,
    )
    assert df["n"].iloc[0] == 0
