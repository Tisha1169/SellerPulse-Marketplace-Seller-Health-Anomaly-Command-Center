# Architecture

## System overview

```mermaid
flowchart TD
    A[Synthetic Data Generator<br/>Python + Faker, seeded] -->|CSV| B[(PostgreSQL — raw load)]
    B --> C[Star Schema<br/>dims + facts]
    C --> D[sql_analytics<br/>daily metrics, rolling + cohort baselines]
    D --> E[Anomaly Detection Engine<br/>ZScore · IQR · CUSUM · IsolationForest]
    E --> F[Ensemble<br/>vote + persistence filter]
    F --> G[(fact_anomaly_flags)]
    G --> H[Scoring<br/>Health Score · Priority Score]
    G --> I[Investigation Queue<br/>tickets + SLA]
    H --> J[Power BI Dashboard]
    I --> J
    I --> K[Streamlit Console]
    L[pipeline/run_daily_pipeline.py] -.orchestrates.-> A
    L -.-> B
    L -.-> D
    L -.-> E
    L -.-> H
    L -.-> I
```

**Why this shape:** raw → warehouse → semantic/star layer → decision layer (anomaly + scoring) → consumption (BI + app) mirrors how a real marketplace ops-analytics stack is layered. Each arrow is a natural place to add a scheduler dependency (Airflow task, dbt model, etc.) without restructuring the rest.

## Star schema (ERD)

```mermaid
erDiagram
    dim_seller ||--o{ fact_orders : "sells via"
    dim_seller ||--o{ dim_product : "lists"
    dim_product ||--o{ fact_orders : "ordered as"
    dim_customer ||--o{ fact_orders : "places"
    dim_date ||--o{ fact_orders : "on"
    fact_orders ||--o| fact_shipments : "ships as"
    fact_orders ||--o| fact_returns : "may be returned as"
    dim_product ||--o{ fact_reviews : "reviewed as"
    dim_seller ||--o{ fact_seller_daily_metrics : "aggregates to"
    dim_seller ||--o{ fact_anomaly_flags : "flagged as"
    fact_anomaly_flags ||--o{ investigation_tickets : "opens"
    dim_seller ||--o{ ground_truth_anomalies : "labeled with"

    dim_seller {
        bigint seller_id PK
        text seller_segment
        text tenure_cohort
        text primary_category
    }
    dim_product {
        bigint product_id PK
        bigint seller_id FK
        text category
    }
    dim_customer {
        bigint customer_id PK
        text customer_segment
    }
    dim_date {
        date date_key PK
    }
    fact_orders {
        bigint order_line_id PK
        bigint seller_id FK
        bigint product_id FK
        bigint customer_id FK
        date order_date FK
        numeric gmv
    }
    fact_shipments {
        bigint shipment_id PK
        bigint order_line_id FK
        boolean is_late
    }
    fact_returns {
        bigint return_id PK
        bigint order_line_id FK
        boolean is_defect_related
    }
    fact_reviews {
        bigint review_id PK
        bigint product_id FK
        smallint rating
    }
    fact_seller_daily_metrics {
        bigint seller_id PK_FK
        date metric_date PK_FK
        numeric defect_rate
        numeric late_shipment_rate
    }
    fact_anomaly_flags {
        bigint flag_id PK
        bigint seller_id FK
        date flag_date
        text anomaly_type
        text method
    }
    investigation_tickets {
        bigint case_id PK
        bigint seller_id FK
        bigint primary_flag_id FK
        text status
    }
    ground_truth_anomalies {
        bigint ground_truth_id PK
        bigint seller_id FK
        text anomaly_type
    }
```

Full DDL with all constraints/indexes: [`database/ddl/`](../database/ddl/).

## Why Health Score and Priority Score are separate

**Seller Health Score** (`scoring/health_score.py`) is a *state* metric: a slow-moving, weighted composite of a seller's operational rates, reviews, and recent anomaly penalty, on 0-100. It answers "how healthy is this seller right now."

**Investigation Priority Score** (`scoring/priority_score.py`) is a *queue-ranking* metric computed per anomaly flag: severity, financial exposure, customer impact, and detection confidence. It answers "which case should an investigator open first this morning."

A seller can have a mediocre health score (Watch tier, nothing new happening this week) with zero investigation urgency — and a seller with a good health score can have a fresh, severe anomaly that must jump the queue today. Merging these into one number would lose that distinction, which is exactly the distinction an operations team needs to act on.

## Why the anomaly engine is layered, not ML-first

1. **Z-score / IQR** (interpretable, first line of defense) — every flag carries a baseline value, observed value, and deviation in the metric's own units. An investigator can read the reason directly.
2. **CUSUM** — catches slow drift that a rolling baseline dilutes (the baseline itself drifts upward with a slow-burn anomaly, weakening z-score's signal). Anchored to a pre-drift reference mean specifically so it doesn't degenerate into z-score.
3. **Isolation Forest** — the only genuinely ML layer, and deliberately last: catches multivariate combinations no single-metric method can see, at the cost of not naming a specific baseline/deviation (mitigated by reporting the top contributing feature via per-feature z-score).
4. **Ensemble** — requires ≥2 independent methods to agree AND persistence across 2+ distinct days before a flag becomes actionable. This wasn't the initial design — it was added after the first evaluation pass (see `docs/evaluation_report.md`) surfaced a genuine multiple-testing problem: at ~5-6M independent daily seller-metric tests, even well-calibrated single-day thresholds produce far more chance exceedances than true anomalies. The persistence requirement is the direct, evidence-driven fix.

**When each method fails**, honestly:
- Z-score assumes roughly symmetric, non-skewed distributions — rate metrics near their floor (mostly 0) violate this, which is why IQR exists alongside it.
- IQR itself fails on low-count integer data (its fence collapses to near-zero) — this is why `order_volume` is explicitly excluded from the IQR method (see `anomaly_engine/zscore_iqr.py`).
- CUSUM's reference anchor is only as good as the "pre-drift" window it's computed from; a seller that was already drifting when monitoring started has no clean anchor.
- Isolation Forest trained globally would just rediscover "small sellers look different from big sellers" as the dominant signal — trained per (tenure_cohort × segment) cohort instead.

## Data quality in production (what's out of scope here)

`pipeline/data_quality_checks.py` runs 13 SQL-based checks and prints a pass/fail report — appropriate for a single-node batch job. A production system would instead: run checks as part of ingestion (e.g. Great Expectations or dbt tests) with per-check alerting, quarantine failing rows into a dead-letter table rather than allowing bad data into `core.*` at all, and track check pass rates over time as their own monitored metric. Not built here to keep scope bounded to what a single portfolio project can credibly own end-to-end.

## Why not Airflow

A daily batch job over a single Postgres instance doesn't need a scheduler with retries, backfills, and a UI — `pipeline/run_daily_pipeline.py` is a linear Python script with the same stage boundaries an Airflow DAG would have (`stage_generate` → `stage_load` → `stage_dq` → `stage_transform` → `stage_detect` → `stage_score` → `stage_investigate` → `stage_evaluate`), so migrating to Airflow later would mean wrapping each stage as a task, not redesigning the pipeline. Building Airflow for a single-node daily job would be technology for its own sake — worth naming explicitly rather than defaulting to "biggest tool available."

## Scalability notes (if this were real production scale)

- `fact_seller_daily_metrics` and the two baseline tables are the highest-cardinality analytical outputs (571K and 5.16M rows respectively at this project's scale) — at real marketplace scale (millions of sellers) these would need partitioning by date and likely a columnar store (BigQuery/Snowflake/Redshift) rather than a single Postgres instance.
- The anomaly engine currently loads full tables into pandas per run; at real scale this would need to run as distributed batch (Spark) or be reformulated as incremental (only re-score the trailing window, not full history) — the SQL layer (window functions, rolling baselines) was written to be portable to a warehouse SQL engine with minimal changes.
- Isolation Forest is retrained per cohort on every run; a production version would persist trained models and only retrain periodically (e.g. weekly), scoring new data against the existing model daily.
