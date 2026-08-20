# SellerPulse — Marketplace Seller Health & Anomaly Command Center

An internal-tooling-style system for detecting deteriorating third-party marketplace
sellers early, prioritizing investigations, and quantifying the operational impact of
early detection — built as a portfolio project modeled on how Amazon Seller
Performance / Flipkart Seller Health / Walmart Marketplace Ops teams actually work.

Full design rationale (architecture diagrams, ERD, scoring methodology, anomaly-
detection trade-offs): [`docs/architecture.md`](docs/architecture.md). Interview
prep and resume framing: [`docs/portfolio_presentation.md`](docs/portfolio_presentation.md).

## What this is

Marketplaces monitor thousands of third-party sellers for deteriorating operational
health — rising defect rates, late shipments, abnormal returns, suspicious review
activity, pricing anomalies — and need to detect it *before* it shows up in customer
complaints. SellerPulse builds that system end-to-end, currently running against
**2,000 synthetic sellers, 20,000 products, and 3.4M orders**:

1. **Synthetic marketplace data** ([`data_generator/`](data_generator/)) — sellers,
   products, customers, orders, shipments, returns, reviews, generated with realistic
   (segment-weighted, right-skewed, non-uniform) distributions, with **160 deliberately
   injected, labeled anomaly episodes** across 8 anomaly types for honest evaluation.
2. **PostgreSQL star schema** ([`database/ddl/`](database/ddl/)) — 4 dimensions, 5+ fact
   tables, with `fact_seller_daily_metrics` (571K rows) as the analytical spine, built on
   window-function-heavy SQL ([`sql_analytics/`](sql_analytics/)): rolling self-baselines,
   peer-cohort baselines, LAG/LEAD trend detection, 10 business-question queries.
3. **Layered anomaly detection engine** ([`anomaly_engine/`](anomaly_engine/)) —
   interpretable statistical methods (z-score, IQR, CUSUM drift detection) plus Isolation
   Forest for multivariate anomalies, combined via ensemble voting + a persistence
   requirement, evaluated against ground truth. See
   [`docs/evaluation_report.md`](docs/evaluation_report.md) for the honest results —
   including a real multiple-testing problem found and fixed during development, not
   glossed over.
4. **Seller Health Score + Investigation Priority Score** ([`scoring/`](scoring/)) —
   0-100 state metric and a separate queue-ranking metric, deliberately not merged
   (see `docs/architecture.md` for why).
5. **Investigation workflow** ([`investigation/`](investigation/)) — SLA-bound ticket
   queue (4,400+ simulated tickets), simulated investigator assignment, root-cause
   categorization, and resolution.
6. **Business impact simulation** ([`pipeline/business_impact_simulation.py`](pipeline/business_impact_simulation.py))
   — labeled-as-estimated comparison of "without early detection" vs. "with early
   detection." Every assumption stated explicitly; see
   [`docs/business_case_study.md`](docs/business_case_study.md).
7. **Streamlit investigation console** ([`streamlit_app/app.py`](streamlit_app/app.py))
   — queue triage + seller drill-down, verified working end-to-end against the live
   database. Power BI dashboard spec in `docs/architecture.md` (not built as a binary
   .pbix in this environment — see note there).

## Repo layout

```
data_generator/   synthetic data generation + anomaly injection (ground truth kept separate)
database/         DDL for the star schema
sql_analytics/    daily metrics SQL, cohort/rolling baselines, 10 business-question queries
anomaly_engine/   z-score/IQR/CUSUM, Isolation Forest, ensemble, evaluation vs ground truth
scoring/          Seller Health Score + Investigation Priority Score
investigation/    ticket queue, SLA engine, simulated investigator workflow
pipeline/         daily orchestrator, data-quality checks, business impact simulation
streamlit_app/    investigator console
tests/            35 tests — unit (ensemble logic, scoring, data generator) + integration
docs/             architecture, data dictionary, evaluation report, business case study,
                  portfolio/interview prep
```

## Tech stack

PostgreSQL · Python (pandas, NumPy, Faker, SQLAlchemy, scikit-learn, statsmodels) ·
SQL (CTEs, window functions, LAG/LEAD, rolling stats) · Streamlit · Docker.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # defaults work as-is for local Docker Postgres
docker compose up -d      # starts Postgres on the port set in .env
```

## Running it

```bash
# Full pipeline: generate data -> load -> validate -> transform -> detect -> score -> investigate -> evaluate
python -m pipeline.run_daily_pipeline

# Re-run just detection/scoring/investigation against already-loaded data (fast — ~2 min)
python -m pipeline.run_daily_pipeline --skip-generate --skip-load

# Investigation console
streamlit run streamlit_app/app.py

# Tests
pytest tests/
```

## Status

All 7 components above are built and verified end-to-end against the live database
(not just individually runnable — the full `run_daily_pipeline` chain works). See
commit history for the incremental build order, and `docs/evaluation_report.md` /
`docs/business_case_study.md` for what the system's own outputs say about itself,
including known limitations.
