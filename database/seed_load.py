"""
Creates the core schema (runs ddl/*.sql in order) and bulk-loads the CSVs produced
by data_generator/run_generator.py into Postgres, in FK-safe order.

Usage: python -m database.seed_load
Requires: docker compose up -d  (or any reachable Postgres matching .env)
"""
import glob
import os

from sqlalchemy import create_engine, text

from data_generator import config as cfg

DB_URL = (
    f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'sellerpulse')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'change_me')}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', 5432)}/"
    f"{os.getenv('POSTGRES_DB', 'sellerpulse')}"
)

DDL_DIR = os.path.join(os.path.dirname(__file__), "ddl")

# (csv filename, target table, columns to parse as dates)
LOAD_ORDER = [
    ("dim_date.csv", "core.dim_date", ["date_key"]),
    ("dim_seller.csv", "core.dim_seller", ["signup_date", "effective_start_date", "effective_end_date"]),
    ("dim_product.csv", "core.dim_product", ["launch_date"]),
    ("dim_customer.csv", "core.dim_customer", ["signup_date"]),
    ("ground_truth_anomalies.csv", "core.ground_truth_anomalies", ["start_date", "end_date"]),
    ("fact_orders.csv", "core.fact_orders", ["order_date"]),
    ("fact_shipments.csv", "core.fact_shipments", ["promised_ship_date", "actual_ship_date", "promised_delivery_date", "actual_delivery_date"]),
    ("fact_returns.csv", "core.fact_returns", ["return_date"]),
    ("fact_reviews.csv", "core.fact_reviews", ["review_date"]),
]


def run_ddl(engine):
    ddl_files = sorted(glob.glob(os.path.join(DDL_DIR, "*.sql")))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
        for f in ddl_files:
            print(f"Running DDL: {os.path.basename(f)}")
            with open(f) as fh:
                conn.execute(text(fh.read()))


def load_csvs(engine):
    for filename, table, date_cols in LOAD_ORDER:
        path = os.path.join(cfg.OUTPUT_DIR, filename)
        if not os.path.exists(path):
            print(f"SKIP {filename} — not found. Run data_generator/run_generator.py first.")
            continue
        schema, table_name = table.split(".")
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            with open(path, "r") as f:
                header = f.readline().strip()
                cols = header.split(",")
                copy_sql = f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')"
                cur.copy_expert(copy_sql, f)
            raw_conn.commit()
            print(f"Loaded {filename} -> {table}")
        finally:
            raw_conn.close()


if __name__ == "__main__":
    engine = create_engine(DB_URL)
    run_ddl(engine)
    load_csvs(engine)
    print("Done.")
