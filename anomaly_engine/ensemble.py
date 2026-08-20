"""
Combines ZScore, IQR, CUSUM, and IsolationForest flags into a single Ensemble
verdict per (seller_id, flag_date, anomaly_type).

Voting rule: a seller-day-anomaly_type is promoted to an Ensemble flag if AT LEAST
2 of the 4 methods fired on it (allowing IsolationForest, which doesn't name a
specific metric, to count toward any anomaly_type the statistical methods raised
that same day for that seller). This is deliberately conservative — it trades
some recall for a large precision gain, which matters operationally because every
Ensemble flag becomes an investigation ticket with a human's time attached to it.

If a seller has 3+ DISTINCT anomaly_types firing (from any method) on the same
day, the case is relabeled Multi_Metric_Deterioration regardless of which single
type had the most votes — a seller failing on three fronts at once is a different,
more urgent situation than any one metric being off.

All four methods' individual flag rows are still written to fact_anomaly_flags
(the audit trail); only rows with method='Ensemble' are eligible to spawn
investigation tickets (investigation/queue_builder.py enforces this).
"""
import pandas as pd

from anomaly_engine.db import get_engine
from anomaly_engine.zscore_iqr import run_zscore, run_iqr
from anomaly_engine.cusum_control_chart import run_cusum
from anomaly_engine.isolation_forest import run_isolation_forest
from anomaly_engine.metric_config import severity_from_score

MIN_METHOD_VOTES = 2
MULTI_METRIC_DISTINCT_TYPE_THRESHOLD = 3


def collect_all_flags() -> pd.DataFrame:
    z = run_zscore()
    i = run_iqr()
    c = run_cusum()
    f = run_isolation_forest()
    frames = [d for d in (z, i, c, f) if d is not None and not d.empty]
    return pd.concat(frames, ignore_index=True)


def build_ensemble(all_flags: pd.DataFrame) -> pd.DataFrame:
    all_flags = all_flags.copy()
    all_flags["flag_date"] = pd.to_datetime(all_flags["flag_date"])

    # Step 1: vote counts per (seller_id, flag_date, anomaly_type)
    votes = (
        all_flags.groupby(["seller_id", "flag_date", "anomaly_type"])
        .agg(
            n_methods=("method", "nunique"),
            methods=("method", lambda s: sorted(set(s))),
            avg_score=("anomaly_score", "mean"),
            max_score=("anomaly_score", "max"),
        )
        .reset_index()
    )

    # Step 2: distinct anomaly_types per (seller_id, flag_date) across ALL flags,
    # regardless of vote count, to detect multi-front deterioration
    distinct_types = (
        all_flags.groupby(["seller_id", "flag_date"])["anomaly_type"].nunique().reset_index(name="n_distinct_types")
    )
    votes = votes.merge(distinct_types, on=["seller_id", "flag_date"], how="left")

    ensemble = votes[votes["n_methods"] >= MIN_METHOD_VOTES].copy()
    ensemble.loc[ensemble["n_distinct_types"] >= MULTI_METRIC_DISTINCT_TYPE_THRESHOLD, "anomaly_type"] = (
        "Multi_Metric_Deterioration"
    )
    # after relabeling, re-collapse duplicate (seller, date) rows that now share the
    # same anomaly_type, keeping the strongest evidence
    ensemble = (
        ensemble.sort_values("max_score", ascending=False)
        .drop_duplicates(subset=["seller_id", "flag_date", "anomaly_type"])
    )

    # pull one representative explanation/affected_metric per group from the
    # highest-scoring underlying flag
    detail = all_flags.sort_values("anomaly_score", ascending=False).drop_duplicates(
        subset=["seller_id", "flag_date", "anomaly_type"]
    )
    ensemble = ensemble.merge(
        detail[["seller_id", "flag_date", "anomaly_type", "affected_metric", "baseline_value",
                "observed_value", "deviation_abs", "deviation_pct"]],
        on=["seller_id", "flag_date"], how="left", suffixes=("", "_detail"),
    )
    # after the Multi_Metric relabel, anomaly_type may no longer match detail's row;
    # keep detail's original metric-specific fields regardless — they're still the
    # strongest single piece of evidence behind this case
    if "anomaly_type_detail" in ensemble.columns:
        ensemble = ensemble.drop(columns=["anomaly_type_detail"])
    ensemble = ensemble.drop_duplicates(subset=["seller_id", "flag_date", "anomaly_type"])

    ensemble["anomaly_score"] = ensemble["avg_score"].round(4)
    ensemble["severity"] = ensemble["anomaly_score"].apply(severity_from_score)
    ensemble["method"] = "Ensemble"
    ensemble["reason_code"] = ensemble["methods"].apply(lambda m: "agreement_of_" + "_".join(m))
    ensemble["explanation"] = ensemble.apply(
        lambda r: (
            f"{int(r['n_methods'])} independent methods ({', '.join(r['methods'])}) agree this is a "
            f"{r['anomaly_type'].replace('_', ' ').lower()} case"
            + (f" ({int(r['n_distinct_types'])} distinct metrics affected)" if r["n_distinct_types"] >= MULTI_METRIC_DISTINCT_TYPE_THRESHOLD else "")
            + f"; combined anomaly score {r['anomaly_score']:.2f}."
        ),
        axis=1,
    )

    cols = [
        "seller_id", "flag_date", "anomaly_type", "affected_metric", "baseline_value", "observed_value",
        "deviation_abs", "deviation_pct", "method", "anomaly_score", "severity", "reason_code", "explanation",
    ]
    return ensemble[cols]


def write_flags_to_db(all_flags: pd.DataFrame, ensemble: pd.DataFrame):
    engine = get_engine()
    combined = pd.concat([all_flags, ensemble], ignore_index=True)
    combined = combined.drop_duplicates(subset=["seller_id", "flag_date", "anomaly_type", "method"])
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE core.fact_anomaly_flags RESTART IDENTITY CASCADE")
    combined.to_sql("fact_anomaly_flags", engine, schema="core", if_exists="append", index=False, chunksize=5000)
    print(f"Wrote {len(combined):,} total flag rows to core.fact_anomaly_flags")


if __name__ == "__main__":
    all_flags = collect_all_flags()
    print(f"Total individual-method flags: {len(all_flags):,}")
    print(all_flags["method"].value_counts())

    ensemble = build_ensemble(all_flags)
    print(f"\nEnsemble flags (>= {MIN_METHOD_VOTES} methods agree): {len(ensemble):,} "
          f"across {ensemble['seller_id'].nunique()} sellers")
    print(ensemble["anomaly_type"].value_counts())
    print(ensemble["severity"].value_counts())

    write_flags_to_db(all_flags, ensemble)
