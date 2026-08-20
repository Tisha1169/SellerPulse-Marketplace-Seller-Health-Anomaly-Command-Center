-- Seller Health Score — grain: one row per seller per day.
-- Kept as a SEPARATE table (not a column bolted onto fact_seller_daily_metrics)
-- because it's a derived, versioned analytical output — component weights can
-- change over time and a full rebuild should not require re-deriving the raw
-- daily metrics.
CREATE TABLE core.seller_health_score (
    seller_id                  BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    score_date                 DATE NOT NULL REFERENCES core.dim_date(date_key),
    health_score                NUMERIC(5,2) NOT NULL CHECK (health_score BETWEEN 0 AND 100),
    health_tier                  TEXT NOT NULL CHECK (health_tier IN ('Healthy','Watch','At_Risk','Critical')),
    defect_component               NUMERIC(5,2) NOT NULL,
    late_shipment_component          NUMERIC(5,2) NOT NULL,
    return_component                   NUMERIC(5,2) NOT NULL,
    cancellation_component               NUMERIC(5,2) NOT NULL,
    review_component                       NUMERIC(5,2) NOT NULL,
    anomaly_penalty_component                NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (seller_id, score_date)
);

CREATE INDEX idx_seller_health_score_date ON core.seller_health_score (score_date);
CREATE INDEX idx_seller_health_score_tier ON core.seller_health_score (health_tier);

COMMENT ON TABLE core.seller_health_score IS
'0-100 Seller Health Score, one row per seller per day. See scoring/health_score.py for weights and normalization method. This is a STATE metric (how healthy is this seller right now) — deliberately separate from investigation_tickets.priority_score, which is a queue-ranking metric. See docs/architecture.md for why the two are not merged.';
