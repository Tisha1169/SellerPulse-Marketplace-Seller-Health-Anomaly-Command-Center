"""
Seller Health Score (0-100) — a STATE metric: how healthy is this seller right now.

Weighted composite of five operational components, each normalized to 0-100
(100 = healthy) via a population-percentile ceiling rather than an arbitrary fixed
cap — the 95th percentile of each metric across ALL seller-days is used as the
"fully unhealthy" reference point, so normalization adapts to this marketplace's
actual data rather than a guessed constant.

Weights (documented, not tuned against ground truth — see docs/architecture.md
for the reasoning):
  - defect_rate            30%  strongest direct proxy for customer trust/safety
  - late_shipment_rate      20%  operationally controllable, directly customer-visible
  - return_rate             15%  overlaps with defect_rate but captures non-defect issues
  - cancellation_rate       10%  weaker signal (often demand-side, not seller-side)
  - review signal           15%  avg_rating + negative_review_rate, blended
  - anomaly penalty         10%  recent (30-day) flag severity, so the score reacts
                                  faster than the underlying rates alone would drift

Deliberately NOT the same thing as Investigation Priority Score: a seller can have
a mediocre health score (a "Watch" tier, nothing new happening) with zero
investigation urgency, or a good health score with a fresh, severe anomaly that
must jump the queue today. See scoring/priority_score.py.
"""
import numpy as np
import pandas as pd

from anomaly_engine.db import get_engine

WEIGHTS = {
    "defect": 0.30,
    "late_shipment": 0.20,
    "return": 0.15,
    "cancellation": 0.10,
    "review": 0.15,
    "anomaly_penalty": 0.10,
}
PERCENTILE_CEILING = 0.95
ANOMALY_LOOKBACK_DAYS = 30
SEVERITY_WEIGHT = {"Low": 1, "Medium": 2, "High": 4, "Critical": 8}

TIER_BANDS = [(80, "Healthy"), (60, "Watch"), (40, "At_Risk"), (0, "Critical")]


def _tier(score: float) -> str:
    for threshold, label in TIER_BANDS:
        if score >= threshold:
            return label
    return "Critical"


def _normalize_bad_is_high(series: pd.Series) -> pd.Series:
    """0 -> 100 (healthy), ceiling (95th pct) or worse -> 0 (unhealthy).

    Rate metrics like defect_rate are heavily zero-inflated (most seller-days
    have zero defects), so the 95th percentile itself is often exactly 0. Falling
    back to "everyone scores 100" in that case would be wrong — it would also
    zero-rate the rare seller-day that genuinely has a bad value. Instead fall
    back to the series' own max as the ceiling; only return the trivial all-100
    result if literally every value is 0.
    """
    ceiling = series.quantile(PERCENTILE_CEILING)
    if ceiling <= 0:
        ceiling = series.max()
        if ceiling <= 0:
            return pd.Series(100.0, index=series.index)
    score = 100 * (1 - (series.clip(lower=0, upper=ceiling) / ceiling))
    return score.clip(0, 100)


def _normalize_bad_is_low(series: pd.Series, floor_reference: float = 1.0) -> pd.Series:
    """e.g. avg_rating: 5.0 -> 100 (healthy), floor_reference or worse -> 0."""
    score = 100 * (series.clip(lower=floor_reference, upper=5.0) - floor_reference) / (5.0 - floor_reference)
    return score.clip(0, 100)


def compute_health_scores() -> pd.DataFrame:
    engine = get_engine()
    metrics = pd.read_sql(
        "SELECT seller_id, metric_date, defect_rate, late_shipment_rate, return_rate, "
        "cancellation_rate, avg_rating, negative_review_rate FROM core.fact_seller_daily_metrics",
        engine, parse_dates=["metric_date"],
    )
    flags = pd.read_sql(
        "SELECT seller_id, flag_date, severity FROM core.fact_anomaly_flags WHERE method = 'Ensemble'",
        engine, parse_dates=["flag_date"],
    )

    metrics["defect_component"] = _normalize_bad_is_high(metrics["defect_rate"])
    metrics["late_shipment_component"] = _normalize_bad_is_high(metrics["late_shipment_rate"])
    metrics["return_component"] = _normalize_bad_is_high(metrics["return_rate"])
    metrics["cancellation_component"] = _normalize_bad_is_high(metrics["cancellation_rate"])

    rating_component = _normalize_bad_is_low(metrics["avg_rating"].fillna(4.3))
    neg_review_component = _normalize_bad_is_high(metrics["negative_review_rate"])
    metrics["review_component"] = (rating_component + neg_review_component) / 2

    # anomaly penalty: severity-weighted count of Ensemble flags in the trailing
    # 30 days, normalized against the population's 95th percentile of that same
    # rolling sum so one severe flag doesn't single-handedly zero out the score
    flags["severity_weight"] = flags["severity"].map(SEVERITY_WEIGHT)
    penalty_frames = []
    for seller_id, grp in metrics.groupby("seller_id"):
        seller_flags = flags[flags["seller_id"] == seller_id].sort_values("flag_date")
        dates = grp["metric_date"].to_numpy()
        penalty = np.zeros(len(dates))
        if not seller_flags.empty:
            fd = seller_flags["flag_date"].to_numpy()
            sw = seller_flags["severity_weight"].to_numpy()
            for idx, d in enumerate(dates):
                window_mask = (fd <= d) & (fd > d - np.timedelta64(ANOMALY_LOOKBACK_DAYS, "D"))
                penalty[idx] = sw[window_mask].sum()
        penalty_frames.append(pd.DataFrame({"seller_id": seller_id, "metric_date": dates, "anomaly_penalty_raw": penalty}))
    penalty_df = pd.concat(penalty_frames, ignore_index=True)
    metrics = metrics.merge(penalty_df, on=["seller_id", "metric_date"], how="left")
    metrics["anomaly_penalty_component"] = _normalize_bad_is_high(metrics["anomaly_penalty_raw"])

    metrics["health_score"] = (
        WEIGHTS["defect"] * metrics["defect_component"]
        + WEIGHTS["late_shipment"] * metrics["late_shipment_component"]
        + WEIGHTS["return"] * metrics["return_component"]
        + WEIGHTS["cancellation"] * metrics["cancellation_component"]
        + WEIGHTS["review"] * metrics["review_component"]
        + WEIGHTS["anomaly_penalty"] * metrics["anomaly_penalty_component"]
    ).round(2)
    metrics["health_tier"] = metrics["health_score"].apply(_tier)

    cols = [
        "seller_id", "metric_date", "health_score", "health_tier",
        "defect_component", "late_shipment_component", "return_component",
        "cancellation_component", "review_component", "anomaly_penalty_component",
    ]
    out = metrics[cols].rename(columns={"metric_date": "score_date"})
    for c in cols[2:]:
        if c != "health_tier":
            out[c] = out[c].round(2)
    return out


def write_health_scores(df: pd.DataFrame):
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE core.seller_health_score")
    df.to_sql("seller_health_score", engine, schema="core", if_exists="append", index=False, chunksize=5000)
    print(f"Wrote {len(df):,} health score rows to core.seller_health_score")


if __name__ == "__main__":
    scores = compute_health_scores()
    print(f"Computed {len(scores):,} seller-day health scores")
    latest_date = scores["score_date"].max()
    latest = scores[scores["score_date"] == latest_date]
    print(f"\nHealth tier distribution as of {latest_date.date()}:")
    print(latest["health_tier"].value_counts())
    print(f"\nMean health score: {latest['health_score'].mean():.1f}")
    write_health_scores(scores)
