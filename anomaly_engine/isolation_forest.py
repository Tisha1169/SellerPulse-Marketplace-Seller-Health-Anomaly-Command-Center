"""
Isolation Forest — multivariate anomaly detection.

Z-score/IQR/CUSUM each look at one metric at a time. Isolation Forest instead
looks at the full daily metric vector per seller-day and can catch a *combination*
that's jointly unusual even when no single metric crosses its own threshold — e.g.
a mild rating dip + a mild order-volume spike + a mild price change together,
each individually inside normal noise, but jointly a distinct pattern (consistent
with, say, a seller quietly cutting corners while chasing volume).

Trained per (tenure_cohort x seller_segment) group rather than globally — a Micro
seller's "normal" is a different shape than a Power seller's, and training one
global forest would just re-learn "small sellers look different from big sellers"
as the dominant signal, drowning out genuine within-cohort anomalies.

Trade-off vs the statistical layer: the score is not directly interpretable in
metric terms (no baseline/observed/deviation the way z-score gives you) — that's
why this project treats it as a second opinion feeding the ensemble, not the
primary output. See docs/architecture.md for the fuller discussion of when NOT
to reach for Isolation Forest.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from anomaly_engine.db import get_engine
from anomaly_engine.metric_config import severity_from_score

FEATURE_COLS = [
    "order_volume", "gmv", "defect_rate", "late_shipment_rate", "cancellation_rate",
    "return_rate", "refund_rate", "avg_rating", "review_velocity", "negative_review_rate",
    "price_volatility", "order_growth_rate_dod",
]
CONTAMINATION = 0.03  # expected anomaly share per cohort; tuned against ground truth in evaluate.py
MIN_GROUP_SIZE = 200  # skip cohorts too small to train a stable forest


def _load_data() -> pd.DataFrame:
    engine = get_engine()
    df = pd.read_sql(
        f"""
        SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.seller_segment,
               {", ".join(FEATURE_COLS)}
        FROM core.fact_seller_daily_metrics f
        JOIN core.dim_seller s ON s.seller_id = f.seller_id
        """,
        engine, parse_dates=["metric_date"],
    )
    return df


def run_isolation_forest(contamination: float = CONTAMINATION) -> pd.DataFrame:
    df = _load_data()
    df[FEATURE_COLS] = df[FEATURE_COLS].fillna(0)

    results = []
    for (cohort, segment), grp in df.groupby(["tenure_cohort", "seller_segment"]):
        if len(grp) < MIN_GROUP_SIZE:
            continue
        X = grp[FEATURE_COLS].to_numpy()
        model = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=42, n_jobs=-1
        )
        model.fit(X)
        raw_score = -model.score_samples(X)  # higher = more anomalous
        pred = model.predict(X)  # -1 = anomaly, 1 = normal

        g = grp.copy()
        g["if_raw_score"] = raw_score
        g["if_is_anomaly"] = pred == -1
        results.append(g)

    if not results:
        return pd.DataFrame()
    scored = pd.concat(results, ignore_index=True)
    flagged = scored[scored["if_is_anomaly"]].copy()

    # normalize raw score to a 0-10 scale per cohort for severity banding, then
    # identify which feature deviated most from that seller's own median as the
    # human-readable "affected_metric" (Isolation Forest itself doesn't name one)
    flagged["anomaly_score"] = (
        (flagged["if_raw_score"] - flagged["if_raw_score"].min())
        / (flagged["if_raw_score"].max() - flagged["if_raw_score"].min() + 1e-9)
        * 10
    ).round(4)
    flagged["severity"] = flagged["anomaly_score"].apply(severity_from_score)

    seller_medians = df.groupby("seller_id")[FEATURE_COLS].transform("median")
    seller_std = df.groupby("seller_id")[FEATURE_COLS].transform("std").replace(0, np.nan)
    per_feature_z = ((df[FEATURE_COLS] - seller_medians) / seller_std).abs().fillna(0)
    df["_top_feature"] = per_feature_z.idxmax(axis=1)
    df["_top_feature_z"] = per_feature_z.max(axis=1)
    flagged = flagged.merge(
        df[["seller_id", "metric_date", "_top_feature", "_top_feature_z"]],
        on=["seller_id", "metric_date"], how="left",
    )

    flagged["affected_metric"] = flagged["_top_feature"]
    flagged["anomaly_type"] = "Multi_Metric_Deterioration"
    flagged["method"] = "IsolationForest"
    flagged["baseline_value"] = np.nan
    flagged["observed_value"] = np.nan
    flagged["deviation_abs"] = np.nan
    flagged["deviation_pct"] = np.nan
    flagged["reason_code"] = "isolation_forest_multivariate_outlier"
    flagged["explanation"] = flagged.apply(
        lambda r: (
            f"Multivariate anomaly across the daily metric vector (isolation score "
            f"{r['anomaly_score']:.2f}/10); {r['_top_feature']} deviated most from this "
            f"seller's own median (z={r['_top_feature_z']:.2f})."
        ),
        axis=1,
    )
    flagged = flagged.rename(columns={"metric_date": "flag_date"})
    cols = [
        "seller_id", "flag_date", "anomaly_type", "affected_metric", "baseline_value", "observed_value",
        "deviation_abs", "deviation_pct", "method", "anomaly_score", "severity", "reason_code", "explanation",
    ]
    return flagged[cols]


if __name__ == "__main__":
    f = run_isolation_forest()
    print(f"Isolation Forest flags: {len(f):,} across {f['seller_id'].nunique() if not f.empty else 0} sellers")
