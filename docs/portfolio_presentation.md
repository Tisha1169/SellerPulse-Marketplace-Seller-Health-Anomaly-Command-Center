# Portfolio Presentation

## Resume bullets

Pick 2-3 depending on the role (Data/BI Analyst vs. Analytics Engineer vs. Data Scientist framing below).

**Analyst-framed:**
- Built an end-to-end marketplace seller-monitoring system (PostgreSQL, SQL, Python) that computes 15+ daily operational KPIs across 2,000 synthetic sellers and 3.4M orders, using window functions (LAG/LEAD, rolling averages, cohort comparisons) to baseline each seller against both its own trend and its peer cohort.
- Designed a transparent, weighted 0-100 Seller Health Score and a separate Investigation Priority Score, and used them to drive an SLA-bound investigation ticket workflow with simulated triage across 4,400+ cases.
- Wrote 10+ analytical SQL queries answering concrete operational questions (fastest-deteriorating sellers, category-level risk, investigator SLA performance, repeat offenders) using CTEs, window functions, and cohort analysis.

**Analytics Engineering-framed:**
- Designed and built a star schema (4 dimensions, 5 fact tables, grain documented per table) in PostgreSQL, with a daily-metrics fact table as the analytical spine feeding a downstream anomaly-detection and scoring layer.
- Built a reproducible, idempotent data pipeline (Python + SQL) — generate → validate (13 automated data-quality checks) → transform → detect → score → investigate — orchestrated as a single script with per-stage logging, runnable end-to-end from a clean environment via Docker.
- Found and fixed a real numeric-overflow bug caused by an incorrect grain assumption (return rate computed against the wrong cohort), rewriting the aggregation to attribute returns to their originating order date instead.

**Data Science-framed:**
- Built a layered anomaly detection engine (z-score, IQR, CUSUM, Isolation Forest, ensemble voting) evaluated against labeled synthetic ground truth, and diagnosed a real multiple-testing problem (raw single-flag precision ~1-2% against a 0.6% true base rate across ~6M independent daily tests) — fixed with a persistence requirement that cut false-positive volume ~4x.
- Documented method-by-method trade-offs (when z-score fails on skewed distributions, when IQR fails on low-count integer data, why CUSUM catches slow drift that rolling baselines miss) and wrote an honest evaluation report distinguishing synthetic-data findings from real-world performance claims.

## LinkedIn / GitHub project description

> **SellerPulse — Marketplace Seller Health & Anomaly Command Center**
> An internal-tooling-style system for detecting deteriorating third-party marketplace sellers early, modeled on how Amazon Seller Performance / Flipkart Seller Health teams operate. Built end-to-end: synthetic marketplace data generator with injected, labeled anomalies (3.4M orders, 2,000 sellers) → PostgreSQL star schema → SQL analytics layer (rolling self-baselines + peer-cohort baselines via window functions) → layered anomaly detection engine (statistical methods + Isolation Forest + ensemble voting) → transparent Seller Health Score and Investigation Priority Score → SLA-bound investigation ticket workflow → Streamlit investigation console. Includes an honest evaluation report against ground truth (precision/recall/F1, a documented multiple-testing finding, and the concrete fix applied) and a simulated business-impact case study with every assumption stated explicitly. Stack: PostgreSQL, Python (pandas, scikit-learn, statsmodels), SQL, Streamlit.
>
> [GitHub repo →](https://github.com/Tisha1169/SellerPulse-Marketplace-Seller-Health-Anomaly-Command-Center)

## Interview preparation

**"Walk me through the project."**
Marketplaces need to catch sellers going bad — rising defects, late shipments, fake reviews — before customers notice. I built the full pipeline a real ops-analytics team would own: synthetic data with known injected anomalies (so I could actually measure detection accuracy, not just eyeball it), a proper dimensional model, SQL that baselines each seller against its own history *and* its peers, a layered detection engine, and a scoring/triage system that turns detections into a workable investigation queue with SLAs.

**"Why a star schema instead of just wide tables?"**
Grain clarity and reuse. `fact_orders` at order-line grain lets me roll up to daily/seller/category at query time without re-deriving anything; a wide denormalized table would either duplicate seller/product attributes millions of times or force me to pick one grain up front. The dimension tables also make cohort analysis a join, not a re-computation.

**"How did you choose your KPI weights for the health score?"**
Documented, not tuned against ground truth — deliberately, because tuning weights against my own synthetic anomalies would be circular (I'd just be learning to detect my own injection function). Defect rate got the highest weight (30%) because it's the most direct proxy for customer trust and safety; cancellation rate got the lowest (10%) because it's often demand-side, not seller-side. In a real deployment, I'd want these tied to actual downstream outcomes (e.g. seller suspension, customer churn) via a regression, not asserted.

**"Your precision numbers look low — walk me through that."**
This is the part of the project I'd lead with, not hide. First pass: raw single-flag precision was ~0.5-1.7%. I diagnosed it as a genuine base-rate/multiple-testing problem, not a bug — at ~5-6M independent daily seller-metric tests and a true anomaly rate of ~0.6%, even a well-calibrated 3-sigma threshold produces far more chance exceedances than real ones. I fixed it two ways: raised individual thresholds, and added a persistence requirement (a signal must repeat across 2+ distinct days before promotion) — which is a legitimate production technique, not a hack. That cut ensemble flag volume roughly 4x. It's still not "high precision" in an absolute sense, and I say so directly in the evaluation report, along with what I'd add next (False Discovery Rate control across each day's test batch — Benjamini-Hochberg — which targets the root cause directly instead of raising bars per method).

**"Why not just use Isolation Forest for everything — isn't ML better?"**
Interpretability, specifically for this operational context. An investigator opening a ticket needs to know *which metric, how far off, versus what baseline* — that's what a z-score/IQR flag gives for free. Isolation Forest's score doesn't map to a specific metric or a human-readable reason on its own, so I only bring it in as a second opinion for genuinely multivariate patterns, and I back into an explanation for it (top contributing feature by per-feature z-score) rather than presenting a bare anomaly score.

**"How would you decide the anomaly threshold in production?"**
Trade off recall against investigator capacity, not against an abstract "accuracy" target. If a team can handle 50 cases/day and my threshold produces 500, the threshold is wrong regardless of what precision/recall say in isolation — the queue-gating decision (only High/Critical severity spawns a ticket) is a direct, explicit capacity control, and I'd tune it against actual investigator throughput data if I had it.

**"Health score vs. priority score — why two numbers?"**
State vs. event. A seller can be chronically mediocre (Watch tier) with nothing new happening — no urgency. A seller with an otherwise-good health score can have a fresh Critical anomaly today that must jump the queue. Merging them would mean either a stable seller's stale ticket outranks a fresh critical one, or vice versa — neither is right, so I kept them separate and let priority score reference severity, financial exposure, customer impact, and detection confidence independently.

**"What would you do differently with more time / real data?"**
Three things, ranked: (1) FDR control on the daily anomaly test batch instead of fixed thresholds — this is the single highest-leverage fix for the precision problem. (2) A feedback loop from investigator resolutions (`False_Positive` vs `Resolved`) back into severity calibration — right now severity is raw statistical magnitude, which I found doesn't correlate cleanly with actual precision (documented in the evaluation report). (3) Incremental/streaming scoring instead of full-history batch recompute every run, for actual production scale.

**"How does this scale to millions of sellers?"**
The SQL layer (window functions, rolling baselines) is portable to any warehouse SQL engine with minimal changes; the bottleneck is the Python anomaly engine loading full tables into pandas per run. At real scale I'd move that to distributed batch (Spark) or reformulate as incremental — only re-score the trailing window each day, not full history — and persist Isolation Forest models instead of retraining every run. All discussed explicitly in `docs/architecture.md`.

**"How did you decide what to deploy for the public demo, given the size limits on free cloud databases?"**
I didn't guess — I grepped the dashboard code (`grep -n "FROM core\." streamlit_app/app.py`) to see exactly which tables it queries and how. That found two things: four raw fact tables (~1.07GB combined) were only ever used for four `COUNT(*)` KPIs, and one 747MB table (`seller_metric_rolling_baseline`) wasn't queried by the dashboard at all. I replaced the four counts with a tiny precomputed summary table and excluded what wasn't used, then trimmed the one large table the app *does* need (`seller_metric_cohort_baseline`) to a 60-day window — wider than the 30-day window the app actually queries, for margin. Result: 2.9GB → 416MB, verified by actually running the export against a throwaway Postgres instance and re-testing every dashboard tab against the reduced data before writing it up, not just estimating the number. The lesson I'd generalize: don't guess at what a "minimal viable dataset" looks like — instrument the actual read pattern first.
