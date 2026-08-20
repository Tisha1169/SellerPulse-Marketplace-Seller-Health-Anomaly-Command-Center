"""
Data quality checks run after every load, before the analytics layer trusts the
data. Each check is a standalone SQL query returning a violation count — zero is
pass. This mirrors how a production system would gate a pipeline: DQ failures
should block downstream steps (or at minimum be loud), not fail silently.

In a real marketplace pipeline these checks would run as part of ingestion
(e.g. via Great Expectations or dbt tests) with alerting on failure and a
quarantine table for bad rows rather than a printed report — see the "Data
quality in production" note in docs/architecture.md for what's out of scope here.
"""
import pandas as pd

from anomaly_engine.db import get_engine

CHECKS = {
    "duplicate_orders": """
        SELECT count(*) FROM (
            SELECT order_line_id, count(*) FROM core.fact_orders GROUP BY order_line_id HAVING count(*) > 1
        ) x
    """,
    "orphan_order_seller_fk": """
        SELECT count(*) FROM core.fact_orders o
        LEFT JOIN core.dim_seller s ON s.seller_id = o.seller_id WHERE s.seller_id IS NULL
    """,
    "orphan_shipment_order_fk": """
        SELECT count(*) FROM core.fact_shipments sh
        LEFT JOIN core.fact_orders o ON o.order_line_id = sh.order_line_id WHERE o.order_line_id IS NULL
    """,
    "orphan_return_order_fk": """
        SELECT count(*) FROM core.fact_returns r
        LEFT JOIN core.fact_orders o ON o.order_line_id = r.order_line_id WHERE o.order_line_id IS NULL
    """,
    "negative_gmv": "SELECT count(*) FROM core.fact_orders WHERE gmv < 0",
    "negative_refund_amount": "SELECT count(*) FROM core.fact_returns WHERE refund_amount < 0",
    "invalid_rating": "SELECT count(*) FROM core.fact_reviews WHERE rating NOT BETWEEN 1 AND 5",
    "delivery_before_ship": """
        SELECT count(*) FROM core.fact_shipments
        WHERE actual_delivery_date IS NOT NULL AND actual_ship_date IS NOT NULL
          AND actual_delivery_date < actual_ship_date
    """,
    "order_date_before_seller_signup": """
        SELECT count(*) FROM core.fact_orders o
        JOIN core.dim_seller s ON s.seller_id = o.seller_id
        WHERE o.order_date < s.signup_date
    """,
    "future_dated_orders": "SELECT count(*) FROM core.fact_orders WHERE order_date > CURRENT_DATE",
    "null_seller_id_orders": "SELECT count(*) FROM core.fact_orders WHERE seller_id IS NULL",
    "return_without_delivered_shipment": """
        SELECT count(*) FROM core.fact_returns r
        LEFT JOIN core.fact_shipments sh ON sh.order_line_id = r.order_line_id
        WHERE sh.order_line_id IS NULL
    """,
    "seller_daily_metrics_rate_out_of_bounds": """
        SELECT count(*) FROM core.fact_seller_daily_metrics
        WHERE defect_rate NOT BETWEEN 0 AND 1 OR late_shipment_rate NOT BETWEEN 0 AND 1
           OR return_rate NOT BETWEEN 0 AND 1 OR cancellation_rate NOT BETWEEN 0 AND 1
    """,
}


def run_checks() -> pd.DataFrame:
    engine = get_engine()
    rows = []
    with engine.connect() as conn:
        for name, sql in CHECKS.items():
            count = conn.exec_driver_sql(sql).scalar()
            rows.append({"check": name, "violations": count, "status": "PASS" if count == 0 else "FAIL"})
    return pd.DataFrame(rows)


def main():
    report = run_checks()
    print(report.to_string(index=False))
    n_fail = (report["status"] == "FAIL").sum()
    if n_fail:
        print(f"\n{n_fail} check(s) FAILED — review before trusting downstream analytics.")
    else:
        print("\nAll data quality checks passed.")
    return report


if __name__ == "__main__":
    main()
