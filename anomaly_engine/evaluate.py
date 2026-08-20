"""
Evaluates detection performance against core.ground_truth_anomalies — the ONLY
place ground truth is ever joined against production flags. This script is the
honest-accounting layer: it measures whether the anomaly engine actually catches
what was injected, not just that it fires often.

A "hit" is defined as: at least one flag for the seller, with a matching
anomaly_type (Multi_Metric_Deterioration matches any injected type, since an
episode injected as e.g. Defect_Rate_Rise can legitimately trigger a multi-metric
relabel if it drags other metrics with it), landing within the injected episode's
[start_date, end_date] window. Detection delay = days between episode start and
the first such hit.

False positives are defined at the SELLER-DAY level: a flag for a seller/date
that falls outside every injected episode for that seller (including sellers with
no injected episode at all, who should never be flagged).

Everything in this file is explicitly about SYNTHETIC ground truth. Nothing here
should ever be described as a measurement of real-world marketplace performance —
see the caveat printed at the bottom of the report and repeated in
docs/evaluation_report.md.
"""
import os

import pandas as pd

from anomaly_engine.db import get_engine

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "evaluation_report.md")


def _load():
    engine = get_engine()
    flags = pd.read_sql("SELECT * FROM core.fact_anomaly_flags", engine, parse_dates=["flag_date"])
    truth = pd.read_sql(
        "SELECT * FROM core.ground_truth_anomalies", engine, parse_dates=["start_date", "end_date"]
    )
    return flags, truth


def _matches_type(flag_type: str, truth_type: str) -> bool:
    if flag_type == truth_type:
        return True
    if flag_type == "Multi_Metric_Deterioration" or truth_type == "Multi_Metric_Deterioration":
        return True
    return False


def evaluate_method(flags: pd.DataFrame, truth: pd.DataFrame, method: str) -> dict:
    m_flags = flags[flags["method"] == method]

    hits, delays, per_type_hit = [], [], {}
    for _, ep in truth.iterrows():
        seller_flags = m_flags[
            (m_flags["seller_id"] == ep["seller_id"])
            & (m_flags["flag_date"] >= ep["start_date"])
            & (m_flags["flag_date"] <= ep["end_date"])
        ]
        seller_flags = seller_flags[seller_flags["anomaly_type"].apply(lambda t: _matches_type(t, ep["anomaly_type"]))]
        detected = not seller_flags.empty
        hits.append(detected)
        per_type_hit.setdefault(ep["anomaly_type"], []).append(detected)
        if detected:
            delay = (seller_flags["flag_date"].min() - ep["start_date"]).days
            delays.append(delay)

    recall = sum(hits) / len(hits) if hits else 0.0
    mean_delay = sum(delays) / len(delays) if delays else None

    # precision: of all flags this method raised, what fraction fall inside SOME
    # injected episode (any seller/type) vs outside every episode for that seller
    truth_windows = truth[["seller_id", "anomaly_type", "start_date", "end_date"]]

    def _is_true_positive(row):
        candidates = truth_windows[truth_windows["seller_id"] == row["seller_id"]]
        for _, ep in candidates.iterrows():
            if ep["start_date"] <= row["flag_date"] <= ep["end_date"] and _matches_type(row["anomaly_type"], ep["anomaly_type"]):
                return True
        return False

    if len(m_flags) > 0:
        tp_mask = m_flags.apply(_is_true_positive, axis=1)
        precision = tp_mask.sum() / len(m_flags)
        false_positive_rate = 1 - precision
    else:
        precision = 0.0
        false_positive_rate = 0.0

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    per_type_recall = {k: sum(v) / len(v) for k, v in per_type_hit.items()}

    return {
        "method": method,
        "n_flags": len(m_flags),
        "n_ground_truth_episodes": len(truth),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(false_positive_rate, 4),
        "mean_detection_delay_days": round(mean_delay, 2) if mean_delay is not None else None,
        "per_type_recall": per_type_recall,
    }


def precision_by_severity(flags: pd.DataFrame, truth: pd.DataFrame, method: str = "Ensemble") -> pd.DataFrame:
    """
    Precision at the raw single-flag level is dominated by chance exceedances —
    with ~570K seller-day observations and only ~0.6% of them truly anomalous, even
    a well-calibrated 3-sigma threshold produces far more chance-noise flags than
    true ones (this is the base-rate problem, not a bug). What actually matters
    operationally is precision among the flags that become investigation tickets —
    i.e. High/Critical severity — since that's the only tier that consumes an
    investigator's time. This breakdown makes that distinction explicit instead of
    hiding behind one blended precision number.
    """
    m_flags = flags[flags["method"] == method].copy()
    truth_windows = truth[["seller_id", "anomaly_type", "start_date", "end_date"]]

    def _is_tp(row):
        candidates = truth_windows[truth_windows["seller_id"] == row["seller_id"]]
        for _, ep in candidates.iterrows():
            if ep["start_date"] <= row["flag_date"] <= ep["end_date"] and _matches_type(row["anomaly_type"], ep["anomaly_type"]):
                return True
        return False

    m_flags["is_tp"] = m_flags.apply(_is_tp, axis=1) if len(m_flags) else []
    rows = []
    for sev in ["Low", "Medium", "High", "Critical"]:
        sub = m_flags[m_flags["severity"] == sev]
        n = len(sub)
        precision = sub["is_tp"].mean() if n else 0.0
        rows.append({"severity": sev, "n_flags": n, "precision": round(precision, 4)})
    return pd.DataFrame(rows)


def confusion_counts(flags: pd.DataFrame, truth: pd.DataFrame, method: str) -> dict:
    m_flags = flags[flags["method"] == method]
    flagged_sellers = set(m_flags["seller_id"].unique())
    truth_sellers = set(truth["seller_id"].unique())
    all_sellers = set(flags["seller_id"].unique()) | truth_sellers

    tp = len(flagged_sellers & truth_sellers)
    fp = len(flagged_sellers - truth_sellers)
    fn = len(truth_sellers - flagged_sellers)
    tn = len(all_sellers - flagged_sellers - truth_sellers)
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn}


def main():
    flags, truth = _load()
    methods = ["ZScore", "IQR", "CUSUM", "IsolationForest", "Ensemble"]

    results = [evaluate_method(flags, truth, m) for m in methods]
    results_df = pd.DataFrame(results)

    print("=" * 100)
    print("ANOMALY DETECTION EVALUATION — SYNTHETIC GROUND TRUTH ONLY, NOT A REAL-WORLD PERFORMANCE CLAIM")
    print("=" * 100)
    print(results_df[["method", "n_flags", "recall", "precision", "f1", "false_positive_rate", "mean_detection_delay_days"]].to_string(index=False))

    print("\nSeller-level confusion matrix (did we flag the seller at all, anywhere, vs. did it have an injected episode):")
    for m in methods:
        cm = confusion_counts(flags, truth, m)
        print(f"  {m:16s}  TP={cm['TP']:5d}  FP={cm['FP']:5d}  FN={cm['FN']:5d}  TN={cm['TN']:5d}")

    print("\nPer-anomaly-type recall (Ensemble):")
    ens_result = next(r for r in results if r["method"] == "Ensemble")
    for t, r in ens_result["per_type_recall"].items():
        print(f"  {t:30s} {r:.2%}")

    sev_precision = precision_by_severity(flags, truth, "Ensemble")
    print("\nEnsemble precision by severity tier (this is the number that matters for the investigation queue):")
    print(sev_precision.to_string(index=False))

    _write_report(results_df, results, methods, flags, truth, sev_precision)
    print(f"\nFull report written to {REPORT_PATH}")


def _write_report(results_df, results, methods, flags, truth, sev_precision):
    lines = []
    lines.append("# Anomaly Detection Evaluation Report\n")
    lines.append(
        "**This entire report is a synthetic-data evaluation.** Ground truth "
        "(`core.ground_truth_anomalies`) is a set of deliberately injected anomaly "
        "episodes created by `data_generator/inject_anomalies.py` — it is not real "
        "marketplace data, and these numbers are not a claim about real-world "
        "detection performance. They measure whether the detection engine correctly "
        "recovers the anomalies it was designed to catch, which is the honest thing "
        "a synthetic evaluation can measure.\n"
    )
    lines.append("## Method comparison\n")
    lines.append(results_df[["method", "n_flags", "recall", "precision", "f1", "false_positive_rate", "mean_detection_delay_days"]].to_markdown(index=False))
    lines.append("\n\n## Seller-level confusion matrix\n")
    lines.append("| Method | TP | FP | FN | TN |")
    lines.append("|---|---|---|---|---|")
    for m in methods:
        cm = confusion_counts(flags, truth, m)
        lines.append(f"| {m} | {cm['TP']} | {cm['FP']} | {cm['FN']} | {cm['TN']} |")

    lines.append("\n## Per-anomaly-type recall (Ensemble)\n")
    lines.append("| Anomaly Type | Recall |")
    lines.append("|---|---|")
    ens_result = next(r for r in results if r["method"] == "Ensemble")
    for t, r in sorted(ens_result["per_type_recall"].items()):
        lines.append(f"| {t} | {r:.1%} |")

    lines.append("\n## Ensemble precision by severity tier\n")
    lines.append(
        "Raw single-flag precision above is dominated by the base-rate problem: with "
        "~570K seller-day observations and only ~0.6% truly anomalous, even a well-"
        "calibrated statistical threshold produces far more chance-noise flags than "
        "true ones. The number that actually matters operationally is precision among "
        "flags that would become investigation tickets — High/Critical severity — "
        "since that's the only tier that consumes investigator time (see "
        "`investigation/queue_builder.py`, which only opens tickets for those tiers).\n"
    )
    lines.append(sev_precision.to_markdown(index=False))

    lines.append("\n## Reading these numbers\n")
    lines.append(
        "- **IQR and ZScore have high recall but low precision at the individual-method level** "
        "— this is expected and is exactly why the ensemble layer exists. A single statistical "
        "method firing on noisy day-to-day variation is not, by itself, evidence worth an "
        "investigator's time.\n"
        "- **CUSUM's value is on slow-drift types** (Defect_Rate_Rise, Return_Rate_Spike) where "
        "z-score/IQR's rolling baseline drifts along with the anomaly and dilutes the signal — "
        "check per-type recall above to see this directly.\n"
        "- **Ensemble trades recall for precision** by requiring >=2 methods to agree. This is "
        "the right trade-off operationally: a missed slow-burn anomaly is recoverable (it will "
        "keep drifting and eventually cross more thresholds), but a flood of low-confidence "
        "single-method flags would overwhelm the investigation queue and erode investigator "
        "trust in the system — false positives are not free.\n"
        "- **Detection delay** is measured from the injected episode's start date to the first "
        "matching flag; lower is better and is the number that would map to 'business impact' "
        "(see docs/business_case_study.md) if a real reactive baseline (e.g. customer complaints) "
        "were, say, 7-10 days.\n"
    )

    lines.append("\n## Known limitations (found during evaluation, not theoretical)\n")
    lines.append(
        "**1. The seller-level confusion matrix is a harsh test on a long horizon, "
        "independent of detector quality.** \"Was this seller ever flagged, anywhere, "
        "across ~300 days of daily monitoring across ~10 metrics\" is close to ~6M "
        "independent statistical tests total. Even a well-calibrated per-test "
        "false-positive rate produces a flag *somewhere* for the large majority of "
        "sellers over a full year — that's multiple-testing, not miscalibration. This "
        "is why the severity-tier precision above (day-level, matched to the true "
        "episode window) is the more honest operational number, and it's still low "
        "(1-3%) for the reason below.\n\n"
        "**2. Severity does not currently correlate cleanly with precision.** Severity "
        "is derived from raw statistical magnitude (z-score / CUSUM cumulative sum / "
        "IQR ratio), and `Multi_Metric_Deterioration` cases are mechanically pushed to "
        "Critical because they aggregate more evidence (more methods, more distinct "
        "metrics) — but more simultaneous metrics firing is not the same as more "
        "likely to be a *true* anomaly when the underlying signal is chance noise "
        "correlated across a seller's own metrics (e.g. a genuinely busy day naturally "
        "moves several rate metrics together). A production system would close this "
        "gap with a feedback loop: use investigator resolutions "
        "(`investigation_tickets.status = 'False_Positive'` vs `'Resolved'`) to "
        "calibrate severity against actual precision (e.g. isotonic regression or a "
        "simple logistic model over the ensemble's raw features), rather than trusting "
        "statistical magnitude as a proxy for likelihood. This project's Investigation "
        "Priority Score (`scoring/priority_score.py`) partially compensates by "
        "weighting method-agreement count and persistence — stronger confidence "
        "proxies than magnitude alone — but does not fully solve it.\n\n"
        "**3. Mitigations applied, and what's left.** Two concrete steps were taken "
        "after the first evaluation pass surfaced this: (a) raising single-method "
        "thresholds (z >= 3.0, CUSUM h = 8 sigma, IQR multiplier = 2.0) and requiring "
        ">=2 methods to agree; (b) requiring persistence — the same (seller, "
        "anomaly_type) must show a flag on 2+ distinct days within a 3-day window, "
        "which cut ensemble flag volume roughly 4x with limited recall loss on "
        "sustained anomaly types. What a production system would add next: False "
        "Discovery Rate control (Benjamini-Hochberg) across each day's full batch of "
        "seller-metric tests, rather than a fixed per-test threshold — this directly "
        "targets the multiple-testing root cause instead of manually raising bars "
        "per method.\n\n"
        "**4. Recall trade-offs from these fixes are visible per-type above.** "
        "`Order_Volume_Shock` recall dropped after excluding it from IQR (IQR is a "
        "poor fit for low-count integer data — its trailing fence collapses to "
        "near-zero for Micro sellers averaging <1 order/day, generating chance flags "
        "on ordinary Poisson variance); `Price_Anomaly` recall is near 0% in this run, "
        "likely because gradual price drift is smoothed by the 28-day rolling baseline "
        "before it crosses any single-day threshold — a CUSUM-only rule tuned "
        "specifically for `avg_price` would be the natural fix, not attempted here to "
        "keep scope bounded.\n"
    )

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
