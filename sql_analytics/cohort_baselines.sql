-- Peer-cohort baseline: same-day mean/std across sellers in the same
-- (tenure_cohort x primary_category x seller_segment) cohort. Used alongside the
-- self-baseline so a seller is only flagged when it deviates from BOTH its own
-- trend and its peers — this is what prevents flagging every seller during a
-- category-wide event (e.g. a holiday-season shipping slowdown that hits everyone).
--
-- Run after seller_daily_metrics.sql. Idempotent: truncates and rebuilds.

DROP TABLE IF EXISTS core.seller_metric_cohort_baseline;

CREATE TABLE core.seller_metric_cohort_baseline AS
WITH long_metrics AS (
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'defect_rate' AS metric_name, f.defect_rate AS observed_value
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'late_shipment_rate', f.late_shipment_rate
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'cancellation_rate', f.cancellation_rate
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'return_rate', f.return_rate
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'refund_rate', f.refund_rate
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'avg_rating', f.avg_rating
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    WHERE f.avg_rating IS NOT NULL
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'review_velocity', f.review_velocity
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'negative_review_rate', f.negative_review_rate
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'avg_price', f.avg_price
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
    WHERE f.avg_price IS NOT NULL
    UNION ALL
    SELECT f.seller_id, f.metric_date, s.tenure_cohort, s.primary_category, s.seller_segment,
           'order_volume', f.order_volume::numeric
    FROM core.fact_seller_daily_metrics f JOIN core.dim_seller s ON s.seller_id = f.seller_id
),
cohort_stats AS (
    SELECT
        tenure_cohort, primary_category, seller_segment, metric_date, metric_name,
        avg(observed_value) AS cohort_mean,
        stddev_samp(observed_value) AS cohort_std,
        count(*) AS cohort_n
    FROM long_metrics
    GROUP BY tenure_cohort, primary_category, seller_segment, metric_date, metric_name
)
SELECT
    lm.seller_id,
    lm.metric_date,
    lm.metric_name,
    lm.observed_value,
    lm.tenure_cohort,
    lm.primary_category,
    lm.seller_segment,
    cs.cohort_mean,
    cs.cohort_std,
    cs.cohort_n,
    CASE
        WHEN cs.cohort_std IS NULL OR cs.cohort_std = 0 OR cs.cohort_n < 5 THEN NULL
        ELSE (lm.observed_value - cs.cohort_mean) / cs.cohort_std
    END AS cohort_zscore
FROM long_metrics lm
JOIN cohort_stats cs
  ON cs.tenure_cohort = lm.tenure_cohort
 AND cs.primary_category = lm.primary_category
 AND cs.seller_segment = lm.seller_segment
 AND cs.metric_date = lm.metric_date
 AND cs.metric_name = lm.metric_name;

CREATE INDEX idx_cohort_baseline_lookup ON core.seller_metric_cohort_baseline (seller_id, metric_name, metric_date);

COMMENT ON TABLE core.seller_metric_cohort_baseline IS
'Peer cohort = (tenure_cohort x primary_category x seller_segment) sellers, same day. cohort_zscore is NULL when fewer than 5 peers exist that day, to avoid unstable estimates from tiny cohorts.';
