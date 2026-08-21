-- Minimal schema for the PUBLIC CLOUD DEMO deployment — a strict subset of
-- database/ddl/*.sql containing only the tables streamlit_app/app.py actually
-- queries (verified by grepping every `FROM core.` in that file before writing
-- this). Deliberately excludes:
--   - dim_product, dim_customer, dim_date       (never queried by the app)
--   - fact_orders, fact_shipments,
--     fact_returns, fact_reviews                 (~1.07GB combined; the app
--                                                  only ever needed 4 COUNT(*)
--                                                  from these, now served by
--                                                  dataset_summary instead)
--   - seller_metric_rolling_baseline             (747MB; not queried by the
--                                                  app anywhere — Seller 360's
--                                                  peer comparison only reads
--                                                  the COHORT baseline)
--   - ground_truth_anomalies                     (only used by
--                                                  anomaly_engine/evaluate.py,
--                                                  a batch script — the app
--                                                  renders the static
--                                                  docs/evaluation_report.md
--                                                  file, not a live query)
--
-- Result: ~2.9GB full local dataset -> ~400MB cloud dataset, with ZERO loss of
-- dashboard functionality. See docs/deployment.md for the full reasoning and
-- deployment/export_cloud_dataset.py for what populates it.
--
-- seller_metric_cohort_baseline is trimmed to a 60-day trailing window at
-- export time (not in this DDL — enforced by the export script's SELECT), since
-- the app only ever queries the latest day (Seller 360) or trailing 30 days
-- (Seller Risk Intelligence). 60 days leaves margin.

CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE core.dim_seller (
    seller_id           BIGINT PRIMARY KEY,
    seller_name         TEXT NOT NULL,
    signup_date         DATE NOT NULL,
    tenure_cohort       TEXT NOT NULL,
    seller_segment      TEXT NOT NULL,
    primary_category    TEXT NOT NULL,
    business_type       TEXT NOT NULL,
    fulfillment_type    TEXT NOT NULL,
    country              TEXT NOT NULL,
    region               TEXT NOT NULL,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    effective_start_date DATE NOT NULL,
    effective_end_date   DATE,
    is_current            BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_dim_seller_segment ON core.dim_seller (seller_segment, primary_category);
CREATE INDEX idx_dim_seller_cohort  ON core.dim_seller (tenure_cohort);

CREATE TABLE core.fact_seller_daily_metrics (
    seller_id             BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    metric_date           DATE NOT NULL,
    order_volume          INTEGER NOT NULL DEFAULT 0,
    gmv                    NUMERIC(14,2) NOT NULL DEFAULT 0,
    avg_order_value        NUMERIC(10,2) NOT NULL DEFAULT 0,
    defect_rate             NUMERIC(10,4) NOT NULL DEFAULT 0,
    late_shipment_rate       NUMERIC(10,4) NOT NULL DEFAULT 0,
    cancellation_rate         NUMERIC(10,4) NOT NULL DEFAULT 0,
    return_rate                NUMERIC(10,4) NOT NULL DEFAULT 0,
    refund_rate                 NUMERIC(10,4) NOT NULL DEFAULT 0,
    avg_rating                   NUMERIC(4,3),
    review_count                  INTEGER NOT NULL DEFAULT 0,
    review_velocity                NUMERIC(8,3) NOT NULL DEFAULT 0,
    negative_review_rate            NUMERIC(6,4) NOT NULL DEFAULT 0,
    avg_price                        NUMERIC(10,2),
    price_volatility                  NUMERIC(8,4) NOT NULL DEFAULT 0,
    order_growth_rate_dod             NUMERIC(8,4),
    PRIMARY KEY (seller_id, metric_date)
);
CREATE INDEX idx_fsdm_date ON core.fact_seller_daily_metrics (metric_date);

CREATE TABLE core.fact_anomaly_flags (
    flag_id           BIGSERIAL PRIMARY KEY,
    seller_id         BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    flag_date         DATE NOT NULL,
    anomaly_type      TEXT NOT NULL,
    affected_metric    TEXT NOT NULL,
    baseline_value       NUMERIC(14,4),
    observed_value        NUMERIC(14,4),
    deviation_abs           NUMERIC(14,4),
    deviation_pct            NUMERIC(14,4),
    method                    TEXT NOT NULL,
    anomaly_score              NUMERIC(12,4) NOT NULL,
    severity                    TEXT NOT NULL,
    reason_code                  TEXT NOT NULL,
    explanation                   TEXT NOT NULL,
    created_at                     TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_faf_seller_date ON core.fact_anomaly_flags (seller_id, flag_date);
CREATE INDEX idx_faf_severity     ON core.fact_anomaly_flags (severity);

CREATE TABLE core.investigation_tickets (
    case_id                BIGINT PRIMARY KEY,
    seller_id               BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    primary_flag_id           BIGINT REFERENCES core.fact_anomaly_flags(flag_id),
    related_flag_ids            BIGINT[] DEFAULT '{}',
    severity                     TEXT NOT NULL,
    priority_score                 NUMERIC(6,2) NOT NULL,
    detected_date                   DATE NOT NULL,
    sla_hours                        INTEGER NOT NULL,
    sla_deadline                      TIMESTAMP NOT NULL,
    status                             TEXT NOT NULL DEFAULT 'New',
    assigned_investigator                TEXT,
    root_cause_category                   TEXT,
    notes                                   TEXT,
    resolution                               TEXT,
    resolved_at                               TIMESTAMP,
    is_sla_breached                            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                                  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at                                   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_it_status   ON core.investigation_tickets (status);
CREATE INDEX idx_it_seller   ON core.investigation_tickets (seller_id);
CREATE INDEX idx_it_priority ON core.investigation_tickets (priority_score DESC);

CREATE TABLE core.seller_health_score (
    seller_id                  BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    score_date                 DATE NOT NULL,
    health_score                NUMERIC(5,2) NOT NULL,
    health_tier                  TEXT NOT NULL,
    defect_component               NUMERIC(5,2) NOT NULL,
    late_shipment_component          NUMERIC(5,2) NOT NULL,
    return_component                   NUMERIC(5,2) NOT NULL,
    cancellation_component               NUMERIC(5,2) NOT NULL,
    review_component                       NUMERIC(5,2) NOT NULL,
    anomaly_penalty_component                NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (seller_id, score_date)
);
CREATE INDEX idx_shs_date ON core.seller_health_score (score_date);
CREATE INDEX idx_shs_tier ON core.seller_health_score (health_tier);

CREATE TABLE core.seller_metric_cohort_baseline (
    seller_id         BIGINT NOT NULL,
    metric_date       DATE NOT NULL,
    metric_name       TEXT NOT NULL,
    observed_value    NUMERIC,
    tenure_cohort     TEXT,
    primary_category  TEXT,
    seller_segment    TEXT,
    cohort_mean       NUMERIC,
    cohort_std        NUMERIC,
    cohort_n          BIGINT,
    cohort_zscore     NUMERIC
);
CREATE INDEX idx_smcb_lookup ON core.seller_metric_cohort_baseline (seller_id, metric_name, metric_date);

CREATE TABLE core.dataset_summary (
    metric_name   TEXT PRIMARY KEY,
    metric_value  BIGINT NOT NULL,
    computed_at   TIMESTAMP NOT NULL DEFAULT now()
);
