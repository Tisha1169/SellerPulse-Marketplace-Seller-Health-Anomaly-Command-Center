"""
Runs the actual data quality checks (pipeline/data_quality_checks.py) against
whatever database is configured — these are integration tests, not unit tests,
and are skipped if no database is reachable (e.g. in a CI environment without
Postgres running) rather than failing noisily.
"""
import pytest
from sqlalchemy.exc import OperationalError

from anomaly_engine.db import get_engine
from pipeline.data_quality_checks import run_checks


def _db_available() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable — start with `docker compose up -d`")


def test_all_data_quality_checks_pass():
    report = run_checks()
    failures = report[report["status"] == "FAIL"]
    assert failures.empty, f"Data quality violations found:\n{failures.to_string(index=False)}"


def test_no_duplicate_orders():
    report = run_checks()
    row = report[report["check"] == "duplicate_orders"].iloc[0]
    assert row["violations"] == 0


def test_seller_daily_metrics_rates_bounded():
    report = run_checks()
    row = report[report["check"] == "seller_daily_metrics_rate_out_of_bounds"].iloc[0]
    assert row["violations"] == 0
