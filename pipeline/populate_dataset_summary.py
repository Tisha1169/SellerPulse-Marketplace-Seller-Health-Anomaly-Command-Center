"""
Populates core.dataset_summary — a one-row-per-metric table the Streamlit app
reads instead of running COUNT(*) against the full raw fact tables. See
database/ddl/05_dataset_summary.sql for why this exists.

Run after any full data load (already wired into pipeline/run_daily_pipeline.py).
"""
from anomaly_engine.db import get_engine

METRICS = {
    "total_sellers": "SELECT count(*) FROM core.dim_seller",
    "total_products": "SELECT count(*) FROM core.dim_product",
    "total_customers": "SELECT count(*) FROM core.dim_customer",
    "total_orders": "SELECT count(*) FROM core.fact_orders",
    "total_shipments": "SELECT count(*) FROM core.fact_shipments",
    "total_returns": "SELECT count(*) FROM core.fact_returns",
    "total_reviews": "SELECT count(*) FROM core.fact_reviews",
}


def populate():
    engine = get_engine()
    with engine.begin() as conn:
        for name, sql in METRICS.items():
            value = conn.exec_driver_sql(sql).scalar()
            conn.exec_driver_sql(
                """
                INSERT INTO core.dataset_summary (metric_name, metric_value, computed_at)
                VALUES (%(name)s, %(value)s, now())
                ON CONFLICT (metric_name) DO UPDATE SET metric_value = EXCLUDED.metric_value, computed_at = now()
                """,
                {"name": name, "value": value},
            )
            print(f"{name}: {value:,}")


if __name__ == "__main__":
    populate()
