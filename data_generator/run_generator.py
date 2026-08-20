"""
Orchestrates the full synthetic data generation pipeline in dependency order:

  dims (seller, product, customer, date) -> ground truth anomaly injection
  -> orders/shipments/returns -> reviews

Run with: python -m data_generator.run_generator
Output CSVs land in data_generator/output/ (gitignored — regenerate, don't commit data).
"""
import os
import time

import pandas as pd

from data_generator import config as cfg
from data_generator.generate_sellers import generate_sellers
from data_generator.generate_products import generate_products
from data_generator.generate_customers import generate_customers, generate_dim_date
from data_generator.inject_anomalies import inject_anomalies
from data_generator.generate_orders_shipments_returns import (
    _order_window,
    generate_order_lines,
    generate_shipments,
    generate_returns,
)
from data_generator.generate_reviews import generate_reviews


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    t0 = time.time()

    print(f"[1/7] Generating {cfg.N_SELLERS} sellers...")
    sellers = generate_sellers()
    sellers.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_seller.csv"), index=False)

    print(f"[2/7] Generating {cfg.N_PRODUCTS} products...")
    products = generate_products(sellers)
    products.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_product.csv"), index=False)

    print(f"[3/7] Generating {cfg.N_CUSTOMERS} customers + date dimension...")
    customers = generate_customers()
    customers.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_customer.csv"), index=False)
    dates = generate_dim_date()
    dates.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_date.csv"), index=False)

    print("[4/7] Injecting ground-truth anomaly episodes...")
    ground_truth = inject_anomalies(sellers)
    ground_truth.to_csv(os.path.join(cfg.OUTPUT_DIR, "ground_truth_anomalies.csv"), index=False)
    print(f"       {len(ground_truth)} episodes across {ground_truth['seller_id'].nunique()} sellers")

    print("[5/7] Generating orders (this is the slow step)...")
    order_dates = _order_window(dates)
    orders = generate_order_lines(sellers, products, customers, order_dates, ground_truth)
    orders.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_orders.csv"), index=False)
    print(f"       {len(orders):,} order lines")

    print("[6/7] Generating shipments + returns...")
    shipments = generate_shipments(orders, sellers, ground_truth)
    shipments.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_shipments.csv"), index=False)
    returns = generate_returns(orders, shipments, sellers, ground_truth)
    returns.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_returns.csv"), index=False)
    print(f"       {len(shipments):,} shipments ({shipments['is_late'].mean():.2%} late), "
          f"{len(returns):,} returns ({returns['is_defect_related'].mean():.2%} defect-related)")

    print("[7/7] Generating reviews...")
    reviews = generate_reviews(orders, ground_truth)
    reviews.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_reviews.csv"), index=False)
    print(f"       {len(reviews):,} reviews (avg rating {reviews['rating'].mean():.2f})")

    print(f"\nDone in {time.time() - t0:.1f}s. Output in {cfg.OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
