"""
CUSUM (cumulative sum) drift detection.

Z-score and IQR compare each day in isolation against a trailing baseline, so
they're strong on sudden spikes but weak on slow, gradual deterioration — e.g. a
defect rate creeping up 0.2%/day for three weeks never produces a single day
extreme enough to trip a z-score threshold, because the rolling baseline itself
drifts upward right along with it. CUSUM instead accumulates small deviations
above a reference level over time, so a slow "boiling frog" trend eventually
crosses the alarm threshold even though no single day looks unusual.

Reference level: the seller's own mean over the first 28 days it has data
(a "pre-drift" anchor), not a trailing rolling mean — that's the whole point,
the reference must NOT drift with the anomaly or CUSUM degenerates into z-score.
"""
import numpy as np
import pandas as pd

from anomaly_engine.db import get_engine
from anomaly_engine.metric_config import METRIC_ANOMALY_MAP, PRIMARY_METRICS, SUPPORTING_METRICS, severity_from_score

ALL_METRICS = PRIMARY_METRICS + SUPPORTING_METRICS
K_SLACK_STD = 0.5   # allowance (in std units) before deviations start accumulating
H_THRESHOLD_STD = 8.0  # alarm threshold, in std units, on the cumulative sum


def _cusum_series(values: np.ndarray, direction: str) -> tuple[np.ndarray, float, float]:
    anchor_n = min(28, max(len(values) // 3, 5))
    anchor_mean = np.nanmean(values[:anchor_n])
    anchor_std = np.nanstd(values[:anchor_n])
    if anchor_std == 0 or np.isnan(anchor_std):
        return np.zeros_like(values), anchor_mean, anchor_std

    k = K_SLACK_STD * anchor_std
    n = len(values)
    c_pos = np.zeros(n)
    c_neg = np.zeros(n)
    for t in range(1, n):
        dev = values[t] - anchor_mean
        c_pos[t] = max(0, c_pos[t - 1] + dev - k)
        c_neg[t] = max(0, c_neg[t - 1] - dev - k)

    if direction == "up":
        cusum = c_pos
    elif direction == "down":
        cusum = c_neg
    else:
        cusum = np.maximum(c_pos, c_neg)
    return cusum, anchor_mean, anchor_std


def run_cusum() -> pd.DataFrame:
    engine = get_engine()
    wide = pd.read_sql(
        "SELECT seller_id, metric_date, " + ", ".join(ALL_METRICS) +
        " FROM core.fact_seller_daily_metrics ORDER BY seller_id, metric_date",
        engine, parse_dates=["metric_date"],
    )
    rows = []
    for metric in ALL_METRICS:
        anomaly_type, direction = METRIC_ANOMALY_MAP[metric]
        sub = wide[["seller_id", "metric_date", metric]].dropna(subset=[metric]).sort_values(["seller_id", "metric_date"])

        out_frames = []
        for seller_id, grp in sub.groupby("seller_id"):
            values = grp[metric].to_numpy(dtype=float)
            if len(values) < 15:
                continue
            cusum, anchor_mean, anchor_std = _cusum_series(values, direction)
            if anchor_std == 0:
                continue
            h = H_THRESHOLD_STD * anchor_std
            g = grp.copy()
            g["cusum"] = cusum
            g["anchor_mean"] = anchor_mean
            g["anchor_std"] = anchor_std
            g["h_threshold"] = h
            out_frames.append(g[g["cusum"] > h])

        if not out_frames:
            continue
        flagged = pd.concat(out_frames, ignore_index=True)
        if flagged.empty:
            continue

        # only keep the first day each seller crosses the threshold per contiguous
        # breach — otherwise every day after the crossing re-fires as its own flag
        flagged = flagged.sort_values(["seller_id", "metric_date"])
        flagged["is_first_breach"] = flagged.groupby("seller_id")["metric_date"].diff().dt.days.fillna(99) > 3
        flagged = flagged[flagged["is_first_breach"]]

        flagged["anomaly_score"] = (flagged["cusum"] / flagged["anchor_std"]).round(4)
        flagged["baseline_value"] = flagged["anchor_mean"]
        flagged["observed_value"] = flagged[metric]
        flagged["deviation_abs"] = flagged["observed_value"] - flagged["anchor_mean"]
        flagged["deviation_pct"] = np.where(
            flagged["anchor_mean"].abs() > 1e-9, flagged["deviation_abs"] / flagged["anchor_mean"].abs() * 100, np.nan
        )
        flagged["affected_metric"] = metric
        flagged["anomaly_type"] = anomaly_type
        flagged["severity"] = flagged["anomaly_score"].apply(severity_from_score)
        flagged["method"] = "CUSUM"
        flagged["reason_code"] = metric + "_cusum_drift"
        flagged["explanation"] = flagged.apply(
            lambda r: (
                f"Cumulative drift in {r['affected_metric']} crossed the CUSUM alarm threshold "
                f"({r['cusum']:.2f} > {r['h_threshold']:.2f}), anchored to a pre-drift mean of "
                f"{r['anchor_mean']:.4f}: sustained gradual deterioration, not a single-day spike."
            ),
            axis=1,
        )
        rows.append(
            flagged[[
                "seller_id", "metric_date", "anomaly_type", "affected_metric", "baseline_value", "observed_value",
                "deviation_abs", "deviation_pct", "method", "anomaly_score", "severity", "reason_code", "explanation",
            ]].rename(columns={"metric_date": "flag_date"})
        )

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    c = run_cusum()
    print(f"CUSUM flags: {len(c):,} across {c['seller_id'].nunique() if not c.empty else 0} sellers")
    if not c.empty:
        print(c["anomaly_type"].value_counts())
