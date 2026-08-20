# SellerPulse — Marketplace Seller Health & Anomaly Command Center

An internal-tooling-style system for detecting deteriorating third-party marketplace
sellers early, prioritizing investigations, and quantifying the operational impact of
early detection — built as a portfolio project modeled on how Amazon Seller
Performance / Flipkart Seller Health / Walmart Marketplace Ops teams actually work.

> Status: **in progress**. This README tracks what's built as of each commit — see
> `docs/` for the full design doc.

## What this is

Marketplaces monitor thousands of third-party sellers for deteriorating operational
health — rising defect rates, late shipments, abnormal returns, suspicious review
activity, pricing anomalies — and need to detect it *before* it shows up in customer
complaints. SellerPulse simulates that system end-to-end:

1. **Synthetic marketplace data** — sellers, products, customers, orders, shipments,
   returns, reviews, generated with realistic (not uniform-random) distributions, with
   **deliberately injected, labeled anomaly episodes** for honest evaluation.
2. **PostgreSQL star schema** — dimensional model with a daily seller-metrics fact
   table as the analytical spine, built with window-function-heavy SQL (rolling
   baselines, cohort comparisons, LAG/LEAD trend detection).
3. **Layered anomaly detection engine** — interpretable statistical methods
   (z-score, IQR, CUSUM-style drift) plus Isolation Forest for multivariate anomalies,
   combined into an ensemble, evaluated against ground truth (precision/recall/F1,
   detection delay, false-positive rate).
4. **Seller Health Score** (0-100, state) and **Investigation Priority Score**
   (queue ranking) — kept deliberately separate; see `docs/`.
5. **Investigation workflow** — SLA-bound ticket queue with simulated investigator
   assignment, root-cause categorization, and resolution.
6. **Business impact simulation** — labeled-as-estimated comparison of "without early
   detection" vs. "with early detection" (orders/GMV/customers protected, investigation
   hours saved). No real marketplace numbers are claimed anywhere.
7. **BI dashboard** (Power BI) + a lightweight Streamlit investigation console.

## Why it's built this way

The full architecture, schema, KPI definitions, scoring methodology, anomaly-detection
design rationale, and week-by-week build plan are in [`docs/architecture.md`](docs/architecture.md).
Short version: every design choice optimizes for being defensible in a Business
Analyst / Data Analyst / Analytics Engineer interview, not for using the most
technology possible.

## Repo layout

```
data_generator/   synthetic data generation + anomaly injection (ground truth kept separate)
database/         DDL for the star schema
sql_analytics/    daily metrics SQL, cohort baselines, business-question queries
anomaly_engine/   z-score/IQR/CUSUM, Isolation Forest, ensemble, evaluation
scoring/          Seller Health Score + Investigation Priority Score
investigation/    ticket queue, SLA engine, simulated investigator workflow
pipeline/         daily orchestrator, data-quality checks, logging
dashboard/        Power BI file + export assets
streamlit_app/    investigator console
tests/            unit + integration tests
docs/             architecture, ERD, evaluation report, business case study
```

## Tech stack

PostgreSQL · Python (pandas, NumPy, Faker, SQLAlchemy, scikit-learn, statsmodels) ·
SQL (CTEs, window functions, LAG/LEAD, rolling stats) · Power BI · Streamlit ·
cron/Python scheduler for the daily job.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DB connection details
docker compose up -d   # starts local Postgres
```

Build progress is tracked via commits — each stage of the pipeline is added and
pushed incrementally.
