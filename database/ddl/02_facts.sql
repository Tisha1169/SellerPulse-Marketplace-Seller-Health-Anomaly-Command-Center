-- SellerPulse star schema — fact tables

-- ============================================================
-- fact_orders — grain: one row per order line item
-- ============================================================
CREATE TABLE core.fact_orders (
    order_line_id   BIGINT PRIMARY KEY,
    order_id        BIGINT NOT NULL,
    seller_id       BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    product_id      BIGINT NOT NULL REFERENCES core.dim_product(product_id),
    customer_id     BIGINT NOT NULL REFERENCES core.dim_customer(customer_id),
    order_date      DATE NOT NULL REFERENCES core.dim_date(date_key),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    gmv             NUMERIC(12,2) NOT NULL CHECK (gmv >= 0),
    order_status    TEXT NOT NULL CHECK (order_status IN ('Placed','Shipped','Delivered','Cancelled','Returned')),
    is_cancelled    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_fact_orders_seller_date ON core.fact_orders (seller_id, order_date);
CREATE INDEX idx_fact_orders_order       ON core.fact_orders (order_id);
CREATE INDEX idx_fact_orders_product     ON core.fact_orders (product_id);

COMMENT ON TABLE core.fact_orders IS 'Grain: one row per order line item. gmv = quantity * unit_price, stored redundantly for query simplicity.';

-- ============================================================
-- fact_shipments — grain: one row per shipment
-- ============================================================
CREATE TABLE core.fact_shipments (
    shipment_id             BIGINT PRIMARY KEY,
    order_line_id           BIGINT NOT NULL REFERENCES core.fact_orders(order_line_id),
    seller_id               BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    promised_ship_date      DATE NOT NULL,
    actual_ship_date        DATE,
    promised_delivery_date  DATE NOT NULL,
    actual_delivery_date    DATE,
    is_late                 BOOLEAN NOT NULL DEFAULT FALSE,
    delay_days               INTEGER NOT NULL DEFAULT 0,
    CHECK (actual_delivery_date IS NULL OR actual_ship_date IS NULL OR actual_delivery_date >= actual_ship_date)
);

CREATE INDEX idx_fact_shipments_seller_date ON core.fact_shipments (seller_id, promised_ship_date);
CREATE INDEX idx_fact_shipments_order       ON core.fact_shipments (order_line_id);

-- ============================================================
-- fact_returns — grain: one row per return event
-- ============================================================
CREATE TABLE core.fact_returns (
    return_id            BIGINT PRIMARY KEY,
    order_line_id        BIGINT NOT NULL REFERENCES core.fact_orders(order_line_id),
    seller_id            BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    return_date          DATE NOT NULL REFERENCES core.dim_date(date_key),
    return_reason_code   TEXT NOT NULL CHECK (return_reason_code IN
        ('Defective','Not_As_Described','Wrong_Item','Changed_Mind','Late_Arrival','Damaged_In_Transit','Other')),
    refund_amount         NUMERIC(12,2) NOT NULL CHECK (refund_amount >= 0),
    is_defect_related     BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_fact_returns_seller_date ON core.fact_returns (seller_id, return_date);

-- ============================================================
-- fact_reviews — grain: one row per review
-- ============================================================
CREATE TABLE core.fact_reviews (
    review_id             BIGINT PRIMARY KEY,
    product_id             BIGINT NOT NULL REFERENCES core.dim_product(product_id),
    seller_id               BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    customer_id              BIGINT NOT NULL REFERENCES core.dim_customer(customer_id),
    review_date               DATE NOT NULL REFERENCES core.dim_date(date_key),
    rating                    SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    is_verified_purchase     BOOLEAN NOT NULL DEFAULT TRUE,
    text_length               INTEGER NOT NULL DEFAULT 0,
    sentiment_flag            TEXT NOT NULL CHECK (sentiment_flag IN ('Positive','Neutral','Negative'))
);

CREATE INDEX idx_fact_reviews_seller_date ON core.fact_reviews (seller_id, review_date);
CREATE INDEX idx_fact_reviews_product     ON core.fact_reviews (product_id);

-- ============================================================
-- fact_seller_daily_metrics — grain: one row per seller per day
-- The analytical spine: everything downstream (anomaly engine, scoring) reads this.
-- ============================================================
CREATE TABLE core.fact_seller_daily_metrics (
    seller_id             BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    metric_date           DATE NOT NULL REFERENCES core.dim_date(date_key),
    order_volume          INTEGER NOT NULL DEFAULT 0,
    gmv                    NUMERIC(14,2) NOT NULL DEFAULT 0,
    avg_order_value        NUMERIC(10,2) NOT NULL DEFAULT 0,
    defect_rate             NUMERIC(6,4) NOT NULL DEFAULT 0,
    late_shipment_rate       NUMERIC(6,4) NOT NULL DEFAULT 0,
    cancellation_rate         NUMERIC(6,4) NOT NULL DEFAULT 0,
    return_rate                NUMERIC(6,4) NOT NULL DEFAULT 0,
    refund_rate                 NUMERIC(6,4) NOT NULL DEFAULT 0,
    avg_rating                   NUMERIC(4,3),
    review_count                  INTEGER NOT NULL DEFAULT 0,
    review_velocity                NUMERIC(8,3) NOT NULL DEFAULT 0,
    negative_review_rate            NUMERIC(6,4) NOT NULL DEFAULT 0,
    avg_price                        NUMERIC(10,2),
    price_volatility                  NUMERIC(8,4) NOT NULL DEFAULT 0,
    order_growth_rate_dod             NUMERIC(8,4),
    PRIMARY KEY (seller_id, metric_date)
);

CREATE INDEX idx_fact_seller_daily_metrics_date ON core.fact_seller_daily_metrics (metric_date);

COMMENT ON TABLE core.fact_seller_daily_metrics IS 'Grain: one row per (seller_id, metric_date). Pre-aggregated daily KPIs computed by sql_analytics/seller_daily_metrics.sql. Rolling baselines and cohort comparisons are computed on top of this table, not stored in it.';
