-- SellerPulse — anomaly flags, investigation tickets, ground truth

-- ============================================================
-- fact_anomaly_flags — grain: one row per (seller_id, date, anomaly_type, method)
-- Append-only audit trail; never overwritten or deleted.
-- ============================================================
CREATE TABLE core.fact_anomaly_flags (
    flag_id           BIGSERIAL PRIMARY KEY,
    seller_id         BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    flag_date         DATE NOT NULL REFERENCES core.dim_date(date_key),
    anomaly_type      TEXT NOT NULL CHECK (anomaly_type IN
        ('Late_Shipment_Spike','Defect_Rate_Rise','Return_Rate_Spike','Review_Velocity_Spike',
         'Rating_Manipulation','Price_Anomaly','Order_Volume_Shock','Multi_Metric_Deterioration')),
    affected_metric    TEXT NOT NULL,
    baseline_value       NUMERIC(14,4),
    observed_value        NUMERIC(14,4),
    deviation_abs           NUMERIC(14,4),
    deviation_pct            NUMERIC(14,4),
    method                    TEXT NOT NULL CHECK (method IN ('ZScore','IQR','CUSUM','IsolationForest','Ensemble')),
    anomaly_score              NUMERIC(12,4) NOT NULL,
    severity                    TEXT NOT NULL CHECK (severity IN ('Low','Medium','High','Critical')),
    reason_code                  TEXT NOT NULL,
    explanation                   TEXT NOT NULL,
    created_at                     TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (seller_id, flag_date, anomaly_type, method)
);

CREATE INDEX idx_fact_anomaly_flags_seller_date ON core.fact_anomaly_flags (seller_id, flag_date);
CREATE INDEX idx_fact_anomaly_flags_severity     ON core.fact_anomaly_flags (severity);

COMMENT ON TABLE core.fact_anomaly_flags IS 'Append-only. One row per method that fired on a given seller/date/anomaly_type. The Ensemble method row is the one investigation_tickets reference.';

-- ============================================================
-- investigation_tickets — grain: one row per case
-- ============================================================
CREATE TABLE core.investigation_tickets (
    case_id                BIGSERIAL PRIMARY KEY,
    seller_id               BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    primary_flag_id           BIGINT REFERENCES core.fact_anomaly_flags(flag_id),
    related_flag_ids            BIGINT[] DEFAULT '{}',
    severity                     TEXT NOT NULL CHECK (severity IN ('Low','Medium','High','Critical')),
    priority_score                 NUMERIC(6,2) NOT NULL,
    detected_date                   DATE NOT NULL,
    sla_hours                        INTEGER NOT NULL,
    sla_deadline                      TIMESTAMP NOT NULL,
    status                             TEXT NOT NULL DEFAULT 'New' CHECK (status IN
        ('New','Investigating','Action_Required','Resolved','False_Positive','Escalated')),
    assigned_investigator                TEXT,
    root_cause_category                   TEXT CHECK (root_cause_category IN
        ('Logistics','Inventory','Pricing','Product_Quality','Seller_Behavior','Review_Anomaly','Data_Quality', NULL)),
    notes                                   TEXT,
    resolution                               TEXT,
    resolved_at                               TIMESTAMP,
    is_sla_breached                            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                                  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at                                   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_investigation_tickets_status   ON core.investigation_tickets (status);
CREATE INDEX idx_investigation_tickets_seller   ON core.investigation_tickets (seller_id);
CREATE INDEX idx_investigation_tickets_priority ON core.investigation_tickets (priority_score DESC);

COMMENT ON TABLE core.investigation_tickets IS 'One case can bundle multiple same-day flags for a seller (primary_flag_id + related_flag_ids). SLA deadline is severity-driven, set at creation.';

-- ============================================================
-- ground_truth_anomalies — grain: one row per injected anomaly episode
-- NEVER joined into production tables directly; used only by anomaly_engine/evaluate.py
-- ============================================================
CREATE TABLE core.ground_truth_anomalies (
    ground_truth_id   BIGSERIAL PRIMARY KEY,
    seller_id          BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    anomaly_type        TEXT NOT NULL,
    affected_metric        TEXT NOT NULL,
    start_date               DATE NOT NULL,
    end_date                  DATE NOT NULL,
    injected_magnitude          NUMERIC(10,4) NOT NULL,
    notes                         TEXT
);

CREATE INDEX idx_ground_truth_seller ON core.ground_truth_anomalies (seller_id);

COMMENT ON TABLE core.ground_truth_anomalies IS 'Synthetic ground truth only. Kept isolated from core.fact_anomaly_flags so evaluation (anomaly_engine/evaluate.py) stays honest and this table is never confused with real detections.';
