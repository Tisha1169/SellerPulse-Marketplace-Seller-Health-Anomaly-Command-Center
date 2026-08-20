-- SellerPulse star schema — dimension tables
-- Grain and design notes are documented inline per table.

CREATE SCHEMA IF NOT EXISTS core;

-- ============================================================
-- dim_seller — grain: one row per seller
-- ============================================================
CREATE TABLE core.dim_seller (
    seller_id           BIGINT PRIMARY KEY,
    seller_name         TEXT NOT NULL,
    signup_date         DATE NOT NULL,
    tenure_cohort       TEXT NOT NULL CHECK (tenure_cohort IN ('New','Growing','Established','Veteran')),
    seller_segment      TEXT NOT NULL CHECK (seller_segment IN ('Micro','Small','Mid','Power')),
    primary_category    TEXT NOT NULL,
    business_type       TEXT NOT NULL CHECK (business_type IN ('Individual','LLC','Corporation')),
    fulfillment_type    TEXT NOT NULL CHECK (fulfillment_type IN ('Marketplace-Fulfilled','Self-Ship')),
    country              TEXT NOT NULL,
    region               TEXT NOT NULL,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    -- SCD2 support for segment changes over time (volume tier can migrate)
    effective_start_date DATE NOT NULL,
    effective_end_date   DATE,
    is_current            BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_dim_seller_segment ON core.dim_seller (seller_segment, primary_category);
CREATE INDEX idx_dim_seller_cohort  ON core.dim_seller (tenure_cohort);

COMMENT ON TABLE core.dim_seller IS 'One row per seller (current + historical SCD2 rows). Peer cohort = tenure_cohort x primary_category x seller_segment.';

-- ============================================================
-- dim_product — grain: one row per product (SKU)
-- ============================================================
CREATE TABLE core.dim_product (
    product_id      BIGINT PRIMARY KEY,
    seller_id       BIGINT NOT NULL REFERENCES core.dim_seller(seller_id),
    product_name    TEXT NOT NULL,
    category        TEXT NOT NULL,
    subcategory     TEXT NOT NULL,
    price_tier      TEXT NOT NULL CHECK (price_tier IN ('Budget','Mid','Premium')),
    list_price      NUMERIC(10,2) NOT NULL CHECK (list_price >= 0),
    launch_date     DATE NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_dim_product_seller   ON core.dim_product (seller_id);
CREATE INDEX idx_dim_product_category ON core.dim_product (category, subcategory);

-- ============================================================
-- dim_customer — grain: one row per customer
-- ============================================================
CREATE TABLE core.dim_customer (
    customer_id      BIGINT PRIMARY KEY,
    signup_date       DATE NOT NULL,
    region            TEXT NOT NULL,
    customer_segment  TEXT NOT NULL CHECK (customer_segment IN ('New','Occasional','Frequent','VIP'))
);

CREATE INDEX idx_dim_customer_region ON core.dim_customer (region);

-- ============================================================
-- dim_date — grain: one row per calendar date
-- ============================================================
CREATE TABLE core.dim_date (
    date_key      DATE PRIMARY KEY,
    day_of_week   SMALLINT NOT NULL,
    day_name      TEXT NOT NULL,
    week_of_year  SMALLINT NOT NULL,
    month_num     SMALLINT NOT NULL,
    month_name    TEXT NOT NULL,
    quarter       SMALLINT NOT NULL,
    year          SMALLINT NOT NULL,
    is_weekend    BOOLEAN NOT NULL,
    is_holiday    BOOLEAN NOT NULL DEFAULT FALSE,
    fiscal_period TEXT NOT NULL
);
