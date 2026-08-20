-- Self-baseline: 28-day trailing rolling mean/std per seller per metric, EXCLUDING
-- the current day (so a metric can't be baselined against itself — that would mask
-- the very anomaly we're trying to detect). Unpivots fact_seller_daily_metrics into
-- long format (one row per seller/date/metric) so the anomaly engine can treat every
-- metric uniformly.
--
-- Run after seller_daily_metrics.sql. Idempotent: truncates and rebuilds.

DROP TABLE IF EXISTS core.seller_metric_rolling_baseline;

CREATE TABLE core.seller_metric_rolling_baseline AS
WITH long_metrics AS (
    SELECT seller_id, metric_date, 'defect_rate' AS metric_name, defect_rate AS observed_value FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'late_shipment_rate', late_shipment_rate FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'cancellation_rate', cancellation_rate FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'return_rate', return_rate FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'refund_rate', refund_rate FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'avg_rating', avg_rating FROM core.fact_seller_daily_metrics WHERE avg_rating IS NOT NULL
    UNION ALL
    SELECT seller_id, metric_date, 'review_velocity', review_velocity FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'negative_review_rate', negative_review_rate FROM core.fact_seller_daily_metrics
    UNION ALL
    SELECT seller_id, metric_date, 'avg_price', avg_price FROM core.fact_seller_daily_metrics WHERE avg_price IS NOT NULL
    UNION ALL
    SELECT seller_id, metric_date, 'order_volume', order_volume::numeric FROM core.fact_seller_daily_metrics
),
windowed AS (
    SELECT
        seller_id,
        metric_date,
        metric_name,
        observed_value,
        avg(observed_value) OVER w28  AS rolling_mean_28d,
        stddev_samp(observed_value) OVER w28 AS rolling_std_28d,
        count(observed_value) OVER w28 AS rolling_n_28d
    FROM long_metrics
    WINDOW w28 AS (
        PARTITION BY seller_id, metric_name ORDER BY metric_date
        ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
    )
)
SELECT
    seller_id,
    metric_date,
    metric_name,
    observed_value,
    rolling_mean_28d,
    rolling_std_28d,
    rolling_n_28d,
    CASE
        WHEN rolling_std_28d IS NULL OR rolling_std_28d = 0 OR rolling_n_28d < 10 THEN NULL
        ELSE (observed_value - rolling_mean_28d) / rolling_std_28d
    END AS self_zscore
FROM windowed;

CREATE INDEX idx_rolling_baseline_lookup ON core.seller_metric_rolling_baseline (seller_id, metric_name, metric_date);

COMMENT ON TABLE core.seller_metric_rolling_baseline IS
'Long-format (seller_id, metric_date, metric_name) rolling self-baseline. self_zscore is NULL until a seller has >=10 trailing observations, avoiding false-confident z-scores on thin history (e.g. a brand-new seller).';
