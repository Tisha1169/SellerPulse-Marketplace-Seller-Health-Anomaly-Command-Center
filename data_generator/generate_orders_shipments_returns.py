"""
Generate fact_orders, fact_shipments, fact_returns.

Simplification documented up front: each generated "order" is a single line item
(order_id == order_line_id). Real marketplaces have multi-item orders; this
generator keeps the 1:1 mapping so the grain stays simple and unambiguous for a
portfolio project, and it's called out in docs/data_dictionary.md.

Anomalous sellers (from ground_truth_anomalies) get their relevant metric's
underlying probability/rate multiplied by injected_magnitude for the duration of
their episode window — that's the mechanism that makes the anomaly detectable at
all, and lets anomaly_engine/evaluate.py measure whether detection actually works.
"""
import os

import numpy as np
import pandas as pd

from data_generator import config as cfg

rng = np.random.default_rng(cfg.RANDOM_SEED + 4)

SEGMENT_QUALITY_MULT = cfg.SEGMENT_QUALITY_MULTIPLIER
BASE = cfg.BASELINE_RATES


def _load_inputs():
    sellers = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_seller.csv"), parse_dates=["signup_date"])
    products = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_product.csv"))
    customers = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_customer.csv"))
    dates = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_date.csv"), parse_dates=["date_key"])
    ground_truth = pd.read_csv(
        os.path.join(cfg.OUTPUT_DIR, "ground_truth_anomalies.csv"),
        parse_dates=["start_date", "end_date"],
    )
    return sellers, products, customers, dates, ground_truth


def _order_window(dates: pd.DataFrame) -> pd.DataFrame:
    cutoff = pd.Timestamp(cfg.SIMULATION_END_DATE) - pd.Timedelta(days=cfg.N_DAYS)
    return dates[dates["date_key"] >= cutoff].reset_index(drop=True)


def _build_seller_day_grid(sellers: pd.DataFrame, order_dates: pd.DataFrame) -> pd.DataFrame:
    """Cross join sellers x dates, keep only rows where the seller has already signed up."""
    sellers_small = sellers[["seller_id", "seller_segment", "signup_date"]].copy()
    sellers_small["key"] = 1
    dd = order_dates[["date_key"]].copy()
    dd["key"] = 1
    grid = sellers_small.merge(dd, on="key").drop(columns="key")
    grid = grid[grid["date_key"] >= grid["signup_date"]].reset_index(drop=True)
    return grid


def _apply_volume_anomaly(grid: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    grid["volume_multiplier"] = 1.0
    episodes = ground_truth[ground_truth["anomaly_type"].isin(["Order_Volume_Shock", "Multi_Metric_Deterioration"])]
    for _, ep in episodes.iterrows():
        mask = (
            (grid["seller_id"] == ep["seller_id"])
            & (grid["date_key"] >= ep["start_date"])
            & (grid["date_key"] <= ep["end_date"])
        )
        mag = ep["injected_magnitude"] if ep["anomaly_type"] == "Order_Volume_Shock" else min(ep["injected_magnitude"], 1.8)
        grid.loc[mask, "volume_multiplier"] = mag
    return grid


def generate_order_lines(sellers, products, customers, order_dates, ground_truth) -> pd.DataFrame:
    grid = _build_seller_day_grid(sellers, order_dates)
    grid = _apply_volume_anomaly(grid, ground_truth)

    base_lambda = grid["seller_segment"].map(cfg.SELLER_SEGMENT_DAILY_ORDER_LAMBDA).to_numpy(dtype=float)
    weekday = pd.DatetimeIndex(grid["date_key"]).dayofweek.to_numpy()
    weekend_factor = np.where(weekday >= 5, 0.85, 1.0)
    day_idx = (pd.DatetimeIndex(grid["date_key"]) - pd.Timestamp(cfg.SIMULATION_END_DATE) + pd.Timedelta(days=cfg.N_DAYS)).days.to_numpy()
    growth_factor = 1.0 + 0.15 * (day_idx / cfg.N_DAYS)  # mild marketplace-wide growth over the window

    lam = base_lambda * weekend_factor * growth_factor * grid["volume_multiplier"].to_numpy()
    lam = np.clip(lam, 0.01, None)
    order_counts = rng.poisson(lam)

    grid["order_count"] = order_counts
    active = grid[grid["order_count"] > 0]

    seller_ids_rep = np.repeat(active["seller_id"].to_numpy(), active["order_count"].to_numpy())
    order_dates_rep = np.repeat(active["date_key"].to_numpy(), active["order_count"].to_numpy())
    n_orders = len(seller_ids_rep)
    print(f"Total order lines to generate: {n_orders:,}")

    # product assignment: pick a random product owned by that seller, per row, grouped for speed
    seller_to_products = products.groupby("seller_id")["product_id"].apply(lambda s: s.to_numpy())
    product_ids = np.empty(n_orders, dtype=np.int64)
    order_seller_series = pd.Series(seller_ids_rep)
    for seller_id, idx in order_seller_series.groupby(order_seller_series).groups.items():
        pool = seller_to_products.get(seller_id)
        if pool is None or len(pool) == 0:
            continue
        idx_arr = np.array(idx)
        product_ids[idx_arr] = rng.choice(pool, size=len(idx_arr))

    # customer assignment weighted by segment activity level
    seg_weight_map = {"New": 1, "Occasional": 2, "Frequent": 4, "VIP": 8}
    cust_weights = customers["customer_segment"].map(seg_weight_map).to_numpy(dtype=float)
    cust_weights = cust_weights / cust_weights.sum()
    customer_ids = rng.choice(customers["customer_id"].to_numpy(), size=n_orders, p=cust_weights)

    quantity = rng.choice([1, 2, 3, 4], size=n_orders, p=[0.70, 0.18, 0.08, 0.04])

    product_price_map = products.set_index("product_id")["list_price"].to_dict()
    base_unit_price = np.array([product_price_map[p] for p in product_ids])
    price_noise = rng.normal(1.0, 0.04, size=n_orders)
    unit_price = np.round(base_unit_price * price_noise, 2)
    unit_price = np.clip(unit_price, 0.5, None)

    gmv = np.round(unit_price * quantity, 2)

    order_line_id = np.arange(1, n_orders + 1)
    order_id = order_line_id.copy()

    df = pd.DataFrame(
        {
            "order_line_id": order_line_id,
            "order_id": order_id,
            "seller_id": seller_ids_rep,
            "product_id": product_ids,
            "customer_id": customer_ids,
            "order_date": order_dates_rep,
            "quantity": quantity,
            "unit_price": unit_price,
            "gmv": gmv,
        }
    )

    # cancellation, perturbed by Multi_Metric_Deterioration episodes
    seller_seg_map = sellers.set_index("seller_id")["seller_segment"].to_dict()
    df["_seg_mult"] = df["seller_id"].map(seller_seg_map).map(SEGMENT_QUALITY_MULT)
    cancel_prob = BASE["cancellation_rate"] * df["_seg_mult"].to_numpy()

    multi_metric = ground_truth[ground_truth["anomaly_type"] == "Multi_Metric_Deterioration"]
    cancel_prob = _apply_episode_multiplier(df, multi_metric, cancel_prob, factor_col="injected_magnitude", scale=0.6)

    df["is_cancelled"] = rng.random(n_orders) < np.clip(cancel_prob, 0, 0.9)

    days_before_end = (pd.Timestamp(cfg.SIMULATION_END_DATE) - pd.DatetimeIndex(df["order_date"])).days
    status = np.where(df["is_cancelled"], "Cancelled", np.where(days_before_end <= 1, "Placed", np.where(days_before_end <= 3, "Shipped", "Delivered")))
    df["order_status"] = status
    df = df.drop(columns="_seg_mult")
    return df


def _apply_episode_multiplier(df, episodes, base_prob, factor_col, scale=1.0):
    """Bump base_prob for rows belonging to a seller during an active anomaly episode."""
    prob = base_prob.copy()
    if episodes.empty:
        return prob
    seller_idx = pd.Series(np.arange(len(df)), index=df["seller_id"]).groupby(level=0).apply(list)
    order_date = pd.DatetimeIndex(df["order_date"])
    for _, ep in episodes.iterrows():
        rows = seller_idx.get(ep["seller_id"])
        if rows is None:
            continue
        rows = np.array(rows)
        in_window = (order_date[rows] >= ep["start_date"]) & (order_date[rows] <= ep["end_date"])
        target_rows = rows[in_window]
        bump = 1.0 + (ep[factor_col] - 1.0) * scale
        prob[target_rows] = prob[target_rows] * bump
    return prob


def generate_shipments(orders: pd.DataFrame, sellers: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    shippable = orders[orders["order_status"] != "Cancelled"].copy()
    n = len(shippable)

    seller_seg_map = sellers.set_index("seller_id")["seller_segment"].to_dict()
    seg_mult = shippable["seller_id"].map(seller_seg_map).map(SEGMENT_QUALITY_MULT).to_numpy()
    late_prob = BASE["late_shipment_rate"] * seg_mult

    late_episodes = ground_truth[ground_truth["anomaly_type"].isin(["Late_Shipment_Spike", "Multi_Metric_Deterioration"])]
    late_prob = _apply_episode_multiplier(shippable.reset_index(drop=True), late_episodes, late_prob, factor_col="injected_magnitude", scale=1.0)

    order_date = pd.DatetimeIndex(shippable["order_date"])
    promised_ship_date = order_date + pd.Timedelta(days=1)
    transit_days = rng.integers(2, 7, size=n)
    promised_delivery_date = promised_ship_date + pd.to_timedelta(transit_days, unit="D")

    is_late = rng.random(n) < np.clip(late_prob, 0, 0.9)
    delay_days = np.where(is_late, rng.integers(1, 10, size=n), 0)

    ship_jitter = rng.integers(0, 2, size=n)  # small non-anomalous variance
    actual_ship_date = promised_ship_date + pd.to_timedelta(ship_jitter, unit="D")
    actual_delivery_date = promised_delivery_date + pd.to_timedelta(delay_days, unit="D")

    df = pd.DataFrame(
        {
            "shipment_id": np.arange(1, n + 1),
            "order_line_id": shippable["order_line_id"].to_numpy(),
            "seller_id": shippable["seller_id"].to_numpy(),
            "promised_ship_date": promised_ship_date.date,
            "actual_ship_date": actual_ship_date.date,
            "promised_delivery_date": promised_delivery_date.date,
            "actual_delivery_date": actual_delivery_date.date,
            "is_late": is_late,
            "delay_days": delay_days,
        }
    )
    return df


REASON_WEIGHTS = {
    "Defective": 0.28,
    "Not_As_Described": 0.18,
    "Wrong_Item": 0.12,
    "Changed_Mind": 0.20,
    "Late_Arrival": 0.10,
    "Damaged_In_Transit": 0.08,
    "Other": 0.04,
}


def generate_returns(orders: pd.DataFrame, shipments: pd.DataFrame, sellers: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    delivered = shipments.merge(orders[["order_line_id", "seller_id", "order_date", "gmv"]], on="order_line_id", suffixes=("", "_o"))
    n_delivered = len(delivered)

    seller_seg_map = sellers.set_index("seller_id")["seller_segment"].to_dict()
    seg_mult = delivered["seller_id"].map(seller_seg_map).map(SEGMENT_QUALITY_MULT).to_numpy()
    return_prob = BASE["return_rate"] * seg_mult

    return_episodes = ground_truth[ground_truth["anomaly_type"].isin(["Return_Rate_Spike", "Defect_Rate_Rise", "Multi_Metric_Deterioration"])]
    return_prob = _apply_episode_multiplier(delivered.reset_index(drop=True), return_episodes, return_prob, factor_col="injected_magnitude", scale=0.9)

    is_returned = rng.random(n_delivered) < np.clip(return_prob, 0, 0.85)
    returned = delivered[is_returned].copy()
    n = len(returned)

    defect_prob = np.full(n, BASE["defect_related_return_share"])
    defect_episodes = ground_truth[ground_truth["anomaly_type"] == "Defect_Rate_Rise"]
    defect_prob = _apply_episode_multiplier(returned.reset_index(drop=True), defect_episodes, defect_prob, factor_col="injected_magnitude", scale=0.5)
    is_defect = rng.random(n) < np.clip(defect_prob, 0, 0.95)

    reason = np.where(
        is_defect,
        "Defective",
        rng.choice(
            [k for k in REASON_WEIGHTS if k != "Defective"],
            size=n,
            p=[v / (1 - REASON_WEIGHTS["Defective"]) for k, v in REASON_WEIGHTS.items() if k != "Defective"],
        ),
    )

    return_offset = rng.integers(3, 21, size=n)
    return_date = pd.DatetimeIndex(returned["order_date"]) + pd.to_timedelta(return_offset, unit="D")
    return_date = np.minimum(return_date, pd.Timestamp(cfg.SIMULATION_END_DATE))

    df = pd.DataFrame(
        {
            "return_id": np.arange(1, n + 1),
            "order_line_id": returned["order_line_id"].to_numpy(),
            "seller_id": returned["seller_id"].to_numpy(),
            "return_date": return_date.date,
            "return_reason_code": reason,
            "refund_amount": returned["gmv"].to_numpy(),
            "is_defect_related": is_defect,
        }
    )
    return df


if __name__ == "__main__":
    sellers, products, customers, dates, ground_truth = _load_inputs()
    order_dates = _order_window(dates)

    orders = generate_order_lines(sellers, products, customers, order_dates, ground_truth)
    orders.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_orders.csv"), index=False)
    print(f"Generated {len(orders):,} order lines")

    shipments = generate_shipments(orders, sellers, ground_truth)
    shipments.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_shipments.csv"), index=False)
    print(f"Generated {len(shipments):,} shipments ({shipments['is_late'].mean():.2%} late)")

    returns = generate_returns(orders, shipments, sellers, ground_truth)
    returns.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_returns.csv"), index=False)
    print(f"Generated {len(returns):,} returns ({returns['is_defect_related'].mean():.2%} defect-related)")
