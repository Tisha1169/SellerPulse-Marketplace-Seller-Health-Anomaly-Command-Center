# Anomaly Detection Evaluation Report

**This entire report is a synthetic-data evaluation.** Ground truth (`core.ground_truth_anomalies`) is a set of deliberately injected anomaly episodes created by `data_generator/inject_anomalies.py` — it is not real marketplace data, and these numbers are not a claim about real-world detection performance. They measure whether the detection engine correctly recovers the anomalies it was designed to catch, which is the honest thing a synthetic evaluation can measure.

## Method comparison

| method          |   n_flags |   recall |   precision |     f1 |   false_positive_rate |   mean_detection_delay_days |
|:----------------|----------:|---------:|------------:|-------:|----------------------:|----------------------------:|
| ZScore          |     33474 |   0.4437 |      0.0062 | 0.0123 |                0.9938 |                        6.75 |
| IQR             |     63118 |   0.3875 |      0.0053 | 0.0105 |                0.9947 |                        7.48 |
| CUSUM           |     19729 |   0.3937 |      0.0057 | 0.0113 |                0.9943 |                        7.71 |
| IsolationForest |     17150 |   0.5375 |      0.0171 | 0.0331 |                0.9829 |                        7.01 |
| Ensemble        |      6241 |   0.3187 |      0.0187 | 0.0354 |                0.9813 |                        9.53 |


## Seller-level confusion matrix

| Method | TP | FP | FN | TN |
|---|---|---|---|---|
| ZScore | 114 | 1299 | 46 | 517 |
| IQR | 157 | 1788 | 3 | 28 |
| CUSUM | 150 | 1729 | 10 | 87 |
| IsolationForest | 153 | 1734 | 7 | 82 |
| Ensemble | 124 | 1384 | 36 | 432 |

## Per-anomaly-type recall (Ensemble)

| Anomaly Type | Recall |
|---|---|
| Defect_Rate_Rise | 43.5% |
| Late_Shipment_Spike | 13.3% |
| Multi_Metric_Deterioration | 68.2% |
| Order_Volume_Shock | 28.6% |
| Price_Anomaly | 0.0% |
| Rating_Manipulation | 15.0% |
| Return_Rate_Spike | 40.0% |
| Review_Velocity_Spike | 35.0% |

## Ensemble precision by severity tier

Raw single-flag precision above is dominated by the base-rate problem: with ~570K seller-day observations and only ~0.6% truly anomalous, even a well-calibrated statistical threshold produces far more chance-noise flags than true ones. The number that actually matters operationally is precision among flags that would become investigation tickets — High/Critical severity — since that's the only tier that consumes investigator time (see `investigation/queue_builder.py`, which only opens tickets for those tiers).

| severity   |   n_flags |   precision |
|:-----------|----------:|------------:|
| Low        |       851 |      0.0282 |
| Medium     |       836 |      0.0275 |
| High       |      1802 |      0.0161 |
| Critical   |      2752 |      0.0149 |

## Reading these numbers

- **IQR and ZScore have high recall but low precision at the individual-method level** — this is expected and is exactly why the ensemble layer exists. A single statistical method firing on noisy day-to-day variation is not, by itself, evidence worth an investigator's time.
- **CUSUM's value is on slow-drift types** (Defect_Rate_Rise, Return_Rate_Spike) where z-score/IQR's rolling baseline drifts along with the anomaly and dilutes the signal — check per-type recall above to see this directly.
- **Ensemble trades recall for precision** by requiring >=2 methods to agree. This is the right trade-off operationally: a missed slow-burn anomaly is recoverable (it will keep drifting and eventually cross more thresholds), but a flood of low-confidence single-method flags would overwhelm the investigation queue and erode investigator trust in the system — false positives are not free.
- **Detection delay** is measured from the injected episode's start date to the first matching flag; lower is better and is the number that would map to 'business impact' (see docs/business_case_study.md) if a real reactive baseline (e.g. customer complaints) were, say, 7-10 days.

## Known limitations (found during evaluation, not theoretical)

**1. The seller-level confusion matrix is a harsh test on a long horizon, independent of detector quality.** "Was this seller ever flagged, anywhere, across ~300 days of daily monitoring across ~10 metrics" is close to ~6M independent statistical tests total. Even a well-calibrated per-test false-positive rate produces a flag *somewhere* for the large majority of sellers over a full year — that's multiple-testing, not miscalibration. This is why `precision_by_severity()` (day-level, matched to the true episode window) is the more honest operational number, and it's still low (1.5-2.8%) for the reason below.

**2. Severity does not currently correlate with precision — Critical is *less* precise than Low in this run.** Severity is derived from raw statistical magnitude (z-score / CUSUM cumulative sum / IQR ratio), and `Multi_Metric_Deterioration` cases are mechanically pushed to Critical because they aggregate more evidence (more methods, more distinct metrics) — but more simultaneous metrics firing is not the same as more likely to be a *true* anomaly when the underlying signal is chance noise correlated across a seller's own metrics (e.g. a genuinely busy day naturally moves several rate metrics together). A production system would close this gap with a feedback loop: use investigator resolutions (`investigation_tickets.status = 'False_Positive'` vs `'Resolved'`) to calibrate severity against actual precision (e.g. isotonic regression or a simple logistic model over the ensemble's raw features), rather than trusting statistical magnitude as a proxy for likelihood. This project's Investigation Priority Score (`scoring/priority_score.py`) partially compensates by weighting method-agreement count and persistence — stronger confidence proxies than magnitude alone — but does not fully solve it.

**3. Mitigations applied, and what's left.** Two concrete steps were taken after the first evaluation pass surfaced this: (a) raising single-method thresholds (z >= 3.0, CUSUM h = 8 sigma, IQR multiplier = 2.0) and requiring >=2 methods to agree; (b) requiring persistence — the same (seller, anomaly_type) must show a flag on 2+ distinct days within a 3-day window, which cut ensemble flag volume from 27.7K to 6.2K with limited recall loss on sustained anomaly types. What a production system would add next: False Discovery Rate control (Benjamini-Hochberg) across each day's full batch of seller-metric tests, rather than a fixed per-test threshold — this directly targets the multiple-testing root cause instead of manually raising bars per method.

**4. Recall trade-offs from these fixes are visible per-type above.** `Order_Volume_Shock` recall dropped after excluding it from IQR (IQR is a poor fit for low-count integer data — its trailing fence collapses to near-zero for Micro sellers averaging <1 order/day, generating chance flags on ordinary Poisson variance); `Price_Anomaly` recall is 0% in this run, likely because gradual price drift is smoothed by the 28-day rolling baseline before it crosses any single-day threshold — a CUSUM-only rule tuned specifically for `avg_price` would be the natural fix, not attempted here to keep scope bounded.
