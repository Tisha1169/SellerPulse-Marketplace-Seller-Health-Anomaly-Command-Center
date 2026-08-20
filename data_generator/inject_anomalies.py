"""
Select a subset of sellers and assign them labeled deterioration episodes.

This is the ground-truth generator: it decides WHICH sellers get WHICH anomaly,
WHEN, and HOW SEVERE — before any order/shipment/return data exists. The fact
generators (generate_orders_shipments_returns.py, generate_reviews.py) read this
table and perturb the affected seller's behavior during the episode window.

Ground truth is written to ground_truth_anomalies.csv / core.ground_truth_anomalies
and is NEVER joined into production fact tables — it exists solely so
anomaly_engine/evaluate.py can score detection performance honestly.
"""
import os

import numpy as np
import pandas as pd

from data_generator import config as cfg

rng = np.random.default_rng(cfg.RANDOM_SEED + 3)

# metric each anomaly type perturbs, and the direction/magnitude range applied
# to that metric's normal rate during the episode.
ANOMALY_METRIC_MAP = {
    "Late_Shipment_Spike": ("late_shipment_rate", (3.0, 7.0)),
    "Defect_Rate_Rise": ("defect_rate", (2.5, 5.0)),
    "Return_Rate_Spike": ("return_rate", (2.5, 6.0)),
    "Review_Velocity_Spike": ("review_velocity", (4.0, 10.0)),
    "Rating_Manipulation": ("avg_rating", (1.15, 1.35)),  # inflated rating, detected via velocity+pattern
    "Price_Anomaly": ("avg_price", (0.5, 1.8)),            # can go up or down
    "Order_Volume_Shock": ("order_volume", (0.15, 0.4)),   # collapse; occasionally a spike (handled below)
    "Multi_Metric_Deterioration": ("multiple", (2.0, 4.0)),
}


def inject_anomalies(sellers_df: pd.DataFrame) -> pd.DataFrame:
    n_sellers = len(sellers_df)
    n_anomalous = int(n_sellers * cfg.PCT_SELLERS_WITH_INJECTED_ANOMALY)

    # Bias selection slightly toward Micro/Small sellers — matches the real-world
    # pattern that operationally weaker sellers are more likely to deteriorate.
    weights = sellers_df["seller_segment"].map({"Micro": 1.4, "Small": 1.2, "Mid": 0.8, "Power": 0.4}).to_numpy()
    weights = weights / weights.sum()
    chosen_sellers = rng.choice(sellers_df["seller_id"].to_numpy(), size=n_anomalous, replace=False, p=weights)

    anomaly_types = rng.choice(
        list(cfg.ANOMALY_TYPE_WEIGHTS.keys()),
        size=n_anomalous,
        p=list(cfg.ANOMALY_TYPE_WEIGHTS.values()),
    )

    rows = []
    for seller_id, anomaly_type in zip(chosen_sellers, anomaly_types):
        episode_len = int(rng.integers(*cfg.ANOMALY_EPISODE_LENGTH_RANGE))
        # episode must fit within the order-generation window, leave room at both ends
        latest_start_offset = cfg.N_DAYS - episode_len - 5
        start_offset = int(rng.integers(5, max(latest_start_offset, 6)))
        start_date = cfg.SIMULATION_END_DATE - pd.Timedelta(days=cfg.N_DAYS - start_offset)
        end_date = start_date + pd.Timedelta(days=episode_len)

        metric, mag_range = ANOMALY_METRIC_MAP[anomaly_type]
        magnitude = round(float(rng.uniform(*mag_range)), 3)

        # Order_Volume_Shock: ~30% of the time it's a spike (fraud/bulk-buy pattern)
        # rather than a collapse, so both directions are represented in ground truth.
        if anomaly_type == "Order_Volume_Shock" and rng.random() < 0.3:
            magnitude = round(float(rng.uniform(2.5, 5.0)), 3)

        rows.append(
            {
                "seller_id": int(seller_id),
                "anomaly_type": anomaly_type,
                "affected_metric": metric,
                "start_date": start_date,
                "end_date": end_date,
                "injected_magnitude": magnitude,
                "notes": f"Synthetic episode: {anomaly_type} over {episode_len} days, magnitude {magnitude}x baseline",
            }
        )

    df = pd.DataFrame(rows)
    df.insert(0, "ground_truth_id", np.arange(1, len(df) + 1))
    return df


if __name__ == "__main__":
    sellers_df = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_seller.csv"))
    df = inject_anomalies(sellers_df)
    df.to_csv(os.path.join(cfg.OUTPUT_DIR, "ground_truth_anomalies.csv"), index=False)
    print(f"Injected {len(df)} anomaly episodes across {df['seller_id'].nunique()} sellers")
    print(df["anomaly_type"].value_counts())
