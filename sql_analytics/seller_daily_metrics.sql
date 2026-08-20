-- Populates core.fact_seller_daily_metrics from the raw fact tables.
-- Grain: one row per (seller_id, metric_date), for every date a seller had
-- at least one order OR was already active (so "zero activity" days are still
-- visible for anomaly detection — a sudden drop to zero orders is itself a signal).
--
-- Run after every raw-data load / refresh. Idempotent: truncates and rebuilds.

TRUNCATE core.fact_seller_daily_metrics;

WITH seller_active_days AS (
    -- every day each seller was active (signup_date .. last date in dim_date),
    -- so days with zero orders still get a row instead of silently disappearing
    SELECT s.seller_id, d.date_key AS metric_date
    FROM core.dim_seller s
    JOIN core.dim_date d
      ON d.date_key >= greatest(s.signup_date, (SELECT min(order_date) FROM core.fact_orders))
     AND d.date_key <= (SELECT max(order_date) FROM core.fact_orders)
),

order_agg AS (
    SELECT
        seller_id,
        order_date AS metric_date,
        count(*) AS order_volume,
        sum(gmv) AS gmv,
        sum(CASE WHEN is_cancelled THEN 1 ELSE 0 END) AS cancelled_orders,
        avg(gmv) AS avg_order_value,
        avg(unit_price) AS avg_price
    FROM core.fact_orders
    GROUP BY seller_id, order_date
),

shipment_agg AS (
    SELECT
        seller_id,
        promised_ship_date AS metric_date,
        count(*) AS shipment_count,
        sum(CASE WHEN is_late THEN 1 ELSE 0 END) AS late_shipments
    FROM core.fact_shipments
    GROUP BY seller_id, promised_ship_date
),

return_agg AS (
    -- Attributed to the ORIGINATING order_date (cohort basis), not the return-processing
    -- date: a return processed weeks later still reflects the quality of the day the
    -- order was placed. This also guarantees return_count <= that day's order_volume.
    SELECT
        fo.seller_id,
        fo.order_date AS metric_date,
        count(*) AS return_count,
        sum(CASE WHEN fr.is_defect_related THEN 1 ELSE 0 END) AS defect_returns,
        sum(fr.refund_amount) AS refund_amount
    FROM core.fact_returns fr
    JOIN core.fact_orders fo ON fo.order_line_id = fr.order_line_id
    GROUP BY fo.seller_id, fo.order_date
),

review_agg AS (
    SELECT
        seller_id,
        review_date AS metric_date,
        count(*) AS review_count,
        avg(rating::numeric) AS avg_rating,
        sum(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative_reviews
    FROM core.fact_reviews
    GROUP BY seller_id, review_date
),

joined AS (
    SELECT
        sad.seller_id,
        sad.metric_date,
        coalesce(o.order_volume, 0)          AS order_volume,
        coalesce(o.gmv, 0)                    AS gmv,
        coalesce(o.avg_order_value, 0)        AS avg_order_value,
        coalesce(o.avg_price, NULL)           AS avg_price,
        coalesce(o.cancelled_orders, 0)       AS cancelled_orders,
        coalesce(sh.shipment_count, 0)        AS shipment_count,
        coalesce(sh.late_shipments, 0)        AS late_shipments,
        coalesce(r.return_count, 0)           AS return_count,
        coalesce(r.defect_returns, 0)         AS defect_returns,
        coalesce(r.refund_amount, 0)          AS refund_amount,
        coalesce(rv.review_count, 0)          AS review_count,
        rv.avg_rating                          AS avg_rating,
        coalesce(rv.negative_reviews, 0)      AS negative_reviews
    FROM seller_active_days sad
    LEFT JOIN order_agg    o  ON o.seller_id = sad.seller_id  AND o.metric_date = sad.metric_date
    LEFT JOIN shipment_agg sh ON sh.seller_id = sad.seller_id AND sh.metric_date = sad.metric_date
    LEFT JOIN return_agg   r  ON r.seller_id = sad.seller_id  AND r.metric_date = sad.metric_date
    LEFT JOIN review_agg   rv ON rv.seller_id = sad.seller_id AND rv.metric_date = sad.metric_date
),

-- 7-day rolling review velocity and price volatility need a window over metric_date
enriched AS (
    SELECT
        j.*,
        avg(review_count) OVER (
            PARTITION BY seller_id ORDER BY metric_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS review_velocity_7d,
        stddev_samp(avg_price) OVER (
            PARTITION BY seller_id ORDER BY metric_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS price_volatility_7d,
        LAG(order_volume) OVER (PARTITION BY seller_id ORDER BY metric_date) AS prev_day_order_volume
    FROM joined j
)

INSERT INTO core.fact_seller_daily_metrics (
    seller_id, metric_date, order_volume, gmv, avg_order_value,
    defect_rate, late_shipment_rate, cancellation_rate, return_rate, refund_rate,
    avg_rating, review_count, review_velocity, negative_review_rate,
    avg_price, price_volatility, order_growth_rate_dod
)
SELECT
    seller_id,
    metric_date,
    order_volume,
    gmv,
    avg_order_value,
    CASE WHEN order_volume > 0 THEN defect_returns::numeric / order_volume ELSE 0 END        AS defect_rate,
    CASE WHEN shipment_count > 0 THEN late_shipments::numeric / shipment_count ELSE 0 END    AS late_shipment_rate,
    CASE WHEN order_volume > 0 THEN cancelled_orders::numeric / order_volume ELSE 0 END      AS cancellation_rate,
    CASE WHEN order_volume > 0 THEN return_count::numeric / order_volume ELSE 0 END          AS return_rate,
    CASE WHEN gmv > 0 THEN refund_amount / gmv ELSE 0 END                                    AS refund_rate,
    avg_rating,
    review_count,
    coalesce(review_velocity_7d, 0),
    CASE WHEN review_count > 0 THEN negative_reviews::numeric / review_count ELSE 0 END      AS negative_review_rate,
    avg_price,
    coalesce(price_volatility_7d, 0),
    CASE WHEN prev_day_order_volume IS NOT NULL AND prev_day_order_volume > 0
         THEN (order_volume - prev_day_order_volume)::numeric / prev_day_order_volume
         ELSE NULL END AS order_growth_rate_dod
FROM enriched;
