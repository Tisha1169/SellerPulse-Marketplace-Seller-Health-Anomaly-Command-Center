"""
Investigation Priority Score — a QUEUE-RANKING metric: who should an investigator
look at first THIS MORNING. Computed per Ensemble anomaly flag, not per seller —
a seller can have multiple open cases with different priority.

Deliberately separate from Seller Health Score (scoring/health_score.py): health
score is a slow-moving state ("how sick is this seller"), priority score is
event-driven ("how urgent is this specific new piece of evidence"). A seller with
health_score=75 (Watch tier, nothing new) should NOT outrank a seller with
health_score=85 whose fresh Critical flag just fired — priority score captures
that, health score alone can't.

Four weighted components, each 0-100:
  - severity_component (35%)   the ensemble flag's own severity/anomaly_score
  - financial_exposure (25%)   seller's trailing 30-day GMV, percentile-ranked —
                                 a flag on a $50K/month seller matters more than
                                 the same flag on a $500/month seller
  - customer_impact (20%)      trailing 30-day order_volume, percentile-ranked —
                                 proxy for how many customers could be affected
  - confidence (20%)           how many independent methods agree (from the
                                 underlying flags feeding this ensemble row) —
                                 more agreement = less likely to be chance noise
                                 (see docs/evaluation_report.md on why raw severity
                                 alone is an unreliable confidence proxy)

SLA hours are derived from severity, not from the priority score itself — SLA is
a commitment made at intake, priority is a live ranking that can shift as new
evidence arrives for a seller already under investigation.
"""
import pandas as pd

from anomaly_engine.db import get_engine

WEIGHTS = {"severity": 0.35, "financial": 0.25, "customer_impact": 0.20, "confidence": 0.20}

SLA_HOURS = {"Critical": 24, "High": 72, "Medium": 120, "Low": 240}


def _percentile_rank_0_100(series: pd.Series) -> pd.Series:
    return (series.rank(pct=True) * 100).round(2)


def compute_priority_scores() -> pd.DataFrame:
    engine = get_engine()
    ensemble_flags = pd.read_sql(
        "SELECT flag_id, seller_id, flag_date, anomaly_type, affected_metric, severity, "
        "anomaly_score, reason_code, explanation FROM core.fact_anomaly_flags WHERE method = 'Ensemble'",
        engine, parse_dates=["flag_date"],
    )
    if ensemble_flags.empty:
        return ensemble_flags

    # confidence proxy: how many underlying methods agreed, parsed back out of
    # reason_code (set by ensemble.py as 'agreement_of_METHOD1_METHOD2...')
    ensemble_flags["n_methods_agreed"] = ensemble_flags["reason_code"].str.split("_").apply(
        lambda parts: len([p for p in parts if p in {"ZScore", "IQR", "CUSUM", "IsolationForest"}])
    )

    trailing = pd.read_sql(
        """
        SELECT seller_id, metric_date,
               sum(gmv) OVER (PARTITION BY seller_id ORDER BY metric_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS gmv_30d,
               sum(order_volume) OVER (PARTITION BY seller_id ORDER BY metric_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS orders_30d
        FROM core.fact_seller_daily_metrics
        """,
        engine, parse_dates=["metric_date"],
    )

    df = ensemble_flags.merge(
        trailing, left_on=["seller_id", "flag_date"], right_on=["seller_id", "metric_date"], how="left"
    )

    severity_rank = {"Low": 25, "Medium": 50, "High": 75, "Critical": 100}
    df["severity_component"] = df["severity"].map(severity_rank).astype(float)
    df["financial_component"] = _percentile_rank_0_100(df["gmv_30d"].fillna(0))
    df["customer_impact_component"] = _percentile_rank_0_100(df["orders_30d"].fillna(0))
    df["confidence_component"] = (df["n_methods_agreed"].clip(upper=4) / 4 * 100).round(2)

    df["priority_score"] = (
        WEIGHTS["severity"] * df["severity_component"]
        + WEIGHTS["financial"] * df["financial_component"]
        + WEIGHTS["customer_impact"] * df["customer_impact_component"]
        + WEIGHTS["confidence"] * df["confidence_component"]
    ).round(2)

    df["sla_hours"] = df["severity"].map(SLA_HOURS)

    cols = [
        "flag_id", "seller_id", "flag_date", "anomaly_type", "affected_metric", "severity",
        "priority_score", "severity_component", "financial_component", "customer_impact_component",
        "confidence_component", "sla_hours", "gmv_30d", "orders_30d", "explanation",
    ]
    return df[cols]


if __name__ == "__main__":
    scores = compute_priority_scores()
    print(f"Computed priority scores for {len(scores):,} ensemble flags")
    if not scores.empty:
        print("\nTop 10 by priority score:")
        top = scores.sort_values("priority_score", ascending=False).head(10)
        print(top[["seller_id", "flag_date", "anomaly_type", "severity", "priority_score", "gmv_30d", "sla_hours"]].to_string(index=False))
