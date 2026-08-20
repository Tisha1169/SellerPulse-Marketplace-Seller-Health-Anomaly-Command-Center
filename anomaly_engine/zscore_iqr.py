"""
Z-score and IQR anomaly detection.

Z-score: uses the self_zscore and cohort_zscore already computed in SQL
(rolling_stats.sql / cohort_baselines.sql). A flag requires deviation from BOTH
the seller's own trend and its peer cohort — this is what keeps a category-wide
event (e.g. every seller's late-shipment rate rising during a holiday surge) from
generating thousands of individually-meaningless flags.

IQR: more robust than z-score for skewed distributions (defect/return rates are
right-skewed — most days are near-zero, so a std-based z-score is distorted by
the skew). Computed as a trailing 28-day rolling IQR per seller per metric,
excluding the current day, same as the self-baseline.

Why both: z-score is the standard, interpretable default; IQR catches cases where
a metric's baseline distribution is too skewed for z-score to be trustworthy
(common for rate metrics near their floor). Neither uses ML — these are meant to
be the transparent, explainable first line of defense before Isolation Forest.
"""
import numpy as np
import pandas as pd

from anomaly_engine.db import get_engine
from anomaly_engine.metric_config import METRIC_ANOMALY_MAP, PRIMARY_METRICS, SUPPORTING_METRICS, severity_from_score

Z_THRESHOLD = 3.0
IQR_MULTIPLIER = 2.0
ALL_METRICS = PRIMARY_METRICS + SUPPORTING_METRICS


def _direction_ok(direction: str, delta: float) -> bool:
    if direction == "up":
        return delta > 0
    if direction == "down":
        return delta < 0
    return True


def run_zscore(z_threshold: float = Z_THRESHOLD) -> pd.DataFrame:
    engine = get_engine()
    self_df = pd.read_sql(
        "SELECT seller_id, metric_date, metric_name, observed_value, rolling_mean_28d, self_zscore "
        "FROM core.seller_metric_rolling_baseline WHERE metric_name = ANY(%(metrics)s)",
        engine, params={"metrics": ALL_METRICS},
    )
    cohort_df = pd.read_sql(
        "SELECT seller_id, metric_date, metric_name, cohort_mean, cohort_zscore "
        "FROM core.seller_metric_cohort_baseline WHERE metric_name = ANY(%(metrics)s)",
        engine, params={"metrics": ALL_METRICS},
    )
    df = self_df.merge(cohort_df, on=["seller_id", "metric_date", "metric_name"], how="inner")
    df = df.dropna(subset=["self_zscore", "cohort_zscore"])

    flagged = df[(df["self_zscore"].abs() >= z_threshold) & (df["cohort_zscore"].abs() >= z_threshold)].copy()

    flagged["delta"] = flagged["observed_value"] - flagged["rolling_mean_28d"]
    flagged["direction_ok"] = flagged.apply(
        lambda r: _direction_ok(METRIC_ANOMALY_MAP[r["metric_name"]][1], r["delta"]), axis=1
    )
    flagged = flagged[flagged["direction_ok"]].drop(columns="direction_ok")

    flagged["anomaly_type"] = flagged["metric_name"].map(lambda m: METRIC_ANOMALY_MAP[m][0])
    flagged["anomaly_score"] = ((flagged["self_zscore"].abs() + flagged["cohort_zscore"].abs()) / 2).round(4)
    flagged["severity"] = flagged["anomaly_score"].apply(severity_from_score)
    flagged["method"] = "ZScore"
    flagged["baseline_value"] = flagged["rolling_mean_28d"]
    flagged["deviation_abs"] = flagged["delta"]
    flagged["deviation_pct"] = np.where(
        flagged["rolling_mean_28d"].abs() > 1e-9,
        flagged["delta"] / flagged["rolling_mean_28d"].abs() * 100,
        np.nan,
    )
    flagged["reason_code"] = flagged["metric_name"] + "_self_and_cohort_zscore"
    flagged["explanation"] = flagged.apply(
        lambda r: (
            f"{r['metric_name']} moved to {r['observed_value']:.4f} vs {r['rolling_mean_28d']:.4f} "
            f"28-day self-baseline (z={r['self_zscore']:.2f}) and {r['cohort_mean']:.4f} peer-cohort "
            f"average (z={r['cohort_zscore']:.2f})."
        ),
        axis=1,
    )

    cols = [
        "seller_id", "metric_date", "anomaly_type", "metric_name", "baseline_value", "observed_value",
        "deviation_abs", "deviation_pct", "method", "anomaly_score", "severity", "reason_code", "explanation",
    ]
    return flagged[cols].rename(columns={"metric_date": "flag_date", "metric_name": "affected_metric"})


def run_iqr(multiplier: float = IQR_MULTIPLIER) -> pd.DataFrame:
    engine = get_engine()
    wide = pd.read_sql(
        "SELECT seller_id, metric_date, " + ", ".join(ALL_METRICS) +
        " FROM core.fact_seller_daily_metrics ORDER BY seller_id, metric_date",
        engine,
    )
    rows = []
    # order_volume is excluded here: it's a low-count integer (Micro sellers average
    # <1 order/day), so its trailing IQR frequently collapses to a tiny fence and
    # produces chance flags on ordinary Poisson variance. Z-score and CUSUM (which
    # use std, not quantile spacing) handle this metric far more robustly — see
    # docs/evaluation_report.md for the flag-volume evidence that motivated this.
    for metric in [m for m in ALL_METRICS if m != "order_volume"]:
        anomaly_type, direction = METRIC_ANOMALY_MAP[metric]
        sub = wide[["seller_id", "metric_date", metric]].dropna(subset=[metric]).copy()
        sub = sub.sort_values(["seller_id", "metric_date"])
        grp = sub.groupby("seller_id")[metric]
        shifted = grp.shift(1)
        roll = shifted.rolling(28, min_periods=10)
        q1 = roll.quantile(0.25).reset_index(drop=True)
        q3 = roll.quantile(0.75).reset_index(drop=True)
        sub = sub.reset_index(drop=True)
        sub["q1"], sub["q3"] = q1, q3
        sub["iqr"] = sub["q3"] - sub["q1"]
        sub["lower"] = sub["q1"] - multiplier * sub["iqr"]
        sub["upper"] = sub["q3"] + multiplier * sub["iqr"]

        below = sub[metric] < sub["lower"]
        above = sub[metric] > sub["upper"]
        if direction == "up":
            mask = above
        elif direction == "down":
            mask = below
        else:
            mask = above | below

        out = sub[mask & sub["iqr"].notna() & (sub["iqr"] > 0)].copy()
        if out.empty:
            continue
        out["deviation_abs"] = np.where(above.loc[out.index], out[metric] - out["upper"], out["lower"] - out[metric])
        # cap: near-zero IQR (a metric that's almost always constant, e.g. 0) can make
        # this ratio blow up to absurd magnitudes that don't add real signal beyond
        # "extremely anomalous" — cap keeps severity banding meaningful and comparable
        # across metrics rather than one metric's score dwarfing everything else.
        out["anomaly_score"] = (out["deviation_abs"].abs() / out["iqr"]).clip(upper=50).round(4)
        out["baseline_value"] = (out["q1"] + out["q3"]) / 2
        out["observed_value"] = out[metric]
        out["affected_metric"] = metric
        out["anomaly_type"] = anomaly_type
        out["severity"] = out["anomaly_score"].apply(severity_from_score)
        out["method"] = "IQR"
        out["deviation_pct"] = np.where(
            out["baseline_value"].abs() > 1e-9, out["deviation_abs"] / out["baseline_value"].abs() * 100, np.nan
        )
        out["reason_code"] = metric + "_iqr_outlier"
        out["explanation"] = out.apply(
            lambda r: (
                f"{r['affected_metric']} = {r['observed_value']:.4f} is outside the 28-day IQR fence "
                f"[{r['lower']:.4f}, {r['upper']:.4f}]."
            ),
            axis=1,
        )
        rows.append(
            out[[
                "seller_id", "metric_date", "anomaly_type", "affected_metric", "baseline_value", "observed_value",
                "deviation_abs", "deviation_pct", "method", "anomaly_score", "severity", "reason_code", "explanation",
            ]].rename(columns={"metric_date": "flag_date"})
        )

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    z = run_zscore()
    print(f"Z-score flags: {len(z):,} across {z['seller_id'].nunique()} sellers")
    print(z["anomaly_type"].value_counts())

    i = run_iqr()
    print(f"\nIQR flags: {len(i):,} across {i['seller_id'].nunique() if not i.empty else 0} sellers")
    if not i.empty:
        print(i["anomaly_type"].value_counts())
