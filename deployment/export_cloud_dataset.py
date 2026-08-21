"""
Exports a size-reduced copy of the local dataset into a cloud Postgres instance
for the public Streamlit Community Cloud demo.

What gets copied, and why: see the header comment in deployment/cloud_schema.sql
— this script is the other half of that plan. Full tables are streamed as-is
for dim_seller, fact_seller_daily_metrics, fact_anomaly_flags,
investigation_tickets, seller_health_score, and dataset_summary.
seller_metric_cohort_baseline is filtered to a 60-day trailing window at export
time (the app never queries further back than 30 days).

Usage:
    export CLOUD_DATABASE_URL="postgresql://user:pass@host:port/dbname"
    python -m deployment.export_cloud_dataset

Reads the LOCAL database via the normal anomaly_engine.db.get_engine() path
(respects .env / POSTGRES_* as always). Writes to CLOUD_DATABASE_URL — kept as
a separate, explicit env var from DATABASE_URL so this script can never be run
by accident against whatever DB the app is currently pointed at.
"""
import os
import time

from sqlalchemy import create_engine

from anomaly_engine.db import get_engine

CLOUD_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "cloud_schema.sql")
COHORT_BASELINE_WINDOW_DAYS = 60

# (table, optional row-filter SQL fragment applied only on the SOURCE side)
FULL_COPY_TABLES = [
    "dim_seller",
    "fact_seller_daily_metrics",
    "fact_anomaly_flags",
    "investigation_tickets",
    "seller_health_score",
    "dataset_summary",
]


def _cloud_engine():
    url = os.getenv("CLOUD_DATABASE_URL")
    if not url:
        raise SystemExit("Set CLOUD_DATABASE_URL to the target cloud Postgres connection string first.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url)


def _stream_table(source_conn, target_conn, table: str, select_sql: str):
    columns = [
        r[0] for r in source_conn.exec_driver_sql(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema='core' AND table_name='{table}' ORDER BY ordinal_position"
        ).fetchall()
    ]
    col_list = ", ".join(columns)

    raw_source = source_conn.connection.dbapi_connection
    raw_target = target_conn.connection.dbapi_connection

    import io
    buf = io.StringIO()
    src_cur = raw_source.cursor()
    src_cur.copy_expert(f"COPY ({select_sql}) TO STDOUT WITH (FORMAT csv, NULL '')", buf)
    buf.seek(0)

    tgt_cur = raw_target.cursor()
    tgt_cur.copy_expert(f"COPY core.{table} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
    raw_target.commit()

    count = target_conn.exec_driver_sql(f"SELECT count(*) FROM core.{table}").scalar()
    print(f"  {table}: {count:,} rows")


def main():
    source_engine = get_engine()
    target_engine = _cloud_engine()

    print("Building cloud schema on target...")
    with open(CLOUD_SCHEMA_PATH) as f, target_engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS core CASCADE")
        conn.exec_driver_sql(f.read())

    print("Streaming full-copy tables...")
    t0 = time.time()
    with source_engine.connect() as sconn, target_engine.connect() as tconn:
        for table in FULL_COPY_TABLES:
            _stream_table(sconn, tconn, table, f"SELECT * FROM core.{table}")

        print(f"Streaming seller_metric_cohort_baseline (trailing {COHORT_BASELINE_WINDOW_DAYS} days only)...")
        _stream_table(
            sconn, tconn, "seller_metric_cohort_baseline",
            f"""
            SELECT * FROM core.seller_metric_cohort_baseline
            WHERE metric_date >= (SELECT max(metric_date) - {COHORT_BASELINE_WINDOW_DAYS} FROM core.fact_seller_daily_metrics)
            """,
        )

    print(f"\nDone in {time.time() - t0:.1f}s.")
    with target_engine.connect() as conn:
        size = conn.exec_driver_sql(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        ).scalar()
        print(f"Cloud database size: {size}")


if __name__ == "__main__":
    main()
