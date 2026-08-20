"""
Generate fact_reviews from delivered orders.

Ratings are left-skewed (most e-commerce reviews are 4-5 stars) by default.
Review_Velocity_Spike inflates how many reviews land in the episode window;
Rating_Manipulation inflates the rating distribution itself (a burst of
suspiciously uniform 5-star ratings) — both are classic fake-review patterns.
"""
import os

import numpy as np
import pandas as pd

from data_generator import config as cfg

rng = np.random.default_rng(cfg.RANDOM_SEED + 5)
BASE = cfg.BASELINE_RATES

# Left-skewed rating distribution: most reviews are positive.
RATING_PROBS = {1: 0.05, 2: 0.06, 3: 0.10, 4: 0.27, 5: 0.52}


def _sample_ratings(n: int) -> np.ndarray:
    return rng.choice(list(RATING_PROBS.keys()), size=n, p=list(RATING_PROBS.values()))


def generate_reviews(orders: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    eligible = orders[orders["order_status"] == "Delivered"].copy()
    n_eligible = len(eligible)

    review_prob = np.full(n_eligible, BASE["review_rate_per_order"])

    velocity_episodes = ground_truth[ground_truth["anomaly_type"] == "Review_Velocity_Spike"]
    order_date = pd.DatetimeIndex(eligible["order_date"])
    seller_idx = pd.Series(np.arange(n_eligible), index=eligible["seller_id"]).groupby(level=0).apply(lambda s: s.to_numpy())

    for _, ep in velocity_episodes.iterrows():
        rows = seller_idx.get(ep["seller_id"])
        if rows is None:
            continue
        in_window = (order_date[rows] >= ep["start_date"]) & (order_date[rows] <= ep["end_date"])
        target = rows[in_window]
        review_prob[target] = np.clip(review_prob[target] * ep["injected_magnitude"], 0, 0.95)

    has_review = rng.random(n_eligible) < review_prob
    reviewed = eligible[has_review].copy()
    n = len(reviewed)

    ratings = _sample_ratings(n)

    # Rating manipulation: force near-uniform 5-star ratings during the episode window
    manip_episodes = ground_truth[ground_truth["anomaly_type"] == "Rating_Manipulation"]
    rev_order_date = pd.DatetimeIndex(reviewed["order_date"])
    rev_seller_idx = pd.Series(np.arange(n), index=reviewed["seller_id"]).groupby(level=0).apply(lambda s: s.to_numpy())
    for _, ep in manip_episodes.iterrows():
        rows = rev_seller_idx.get(ep["seller_id"])
        if rows is None:
            continue
        in_window = (rev_order_date[rows] >= ep["start_date"]) & (rev_order_date[rows] <= ep["end_date"])
        target = rows[in_window]
        manipulated = rng.choice([5, 5, 5, 4], size=len(target))  # suspiciously clustered at 5
        ratings[target] = manipulated

    review_offset = rng.integers(1, 14, size=n)
    review_date = pd.DatetimeIndex(reviewed["order_date"]) + pd.to_timedelta(review_offset, unit="D")
    review_date = np.minimum(review_date, pd.Timestamp(cfg.SIMULATION_END_DATE))

    is_verified = rng.random(n) < 0.92
    text_length = np.round(np.clip(rng.normal(120, 60, size=n), 5, None)).astype(int)
    sentiment = np.select(
        [ratings <= 2, ratings == 3],
        ["Negative", "Neutral"],
        default="Positive",
    )
    customer_ids = reviewed["customer_id"].to_numpy()

    df = pd.DataFrame(
        {
            "review_id": np.arange(1, n + 1),
            "product_id": reviewed["product_id"].to_numpy(),
            "seller_id": reviewed["seller_id"].to_numpy(),
            "customer_id": customer_ids,
            "review_date": review_date.date,
            "rating": ratings,
            "is_verified_purchase": is_verified,
            "text_length": text_length,
            "sentiment_flag": sentiment,
        }
    )
    return df


if __name__ == "__main__":
    orders = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "fact_orders.csv"), parse_dates=["order_date"])
    ground_truth = pd.read_csv(
        os.path.join(cfg.OUTPUT_DIR, "ground_truth_anomalies.csv"), parse_dates=["start_date", "end_date"]
    )
    reviews = generate_reviews(orders, ground_truth)
    reviews.to_csv(os.path.join(cfg.OUTPUT_DIR, "fact_reviews.csv"), index=False)
    print(f"Generated {len(reviews):,} reviews (avg rating {reviews['rating'].mean():.2f})")
