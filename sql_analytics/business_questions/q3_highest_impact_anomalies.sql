-- Q3: Which anomalies have the highest financial/customer impact?
-- Uses the priority score components already computed at ticket-creation time.
SELECT
    t.case_id,
    t.seller_id,
    s.seller_name,
    f.anomaly_type,
    f.affected_metric,
    t.severity,
    t.priority_score,
    t.detected_date,
    t.status,
    round(m.gmv, 2) AS gmv_on_detection_day,
    m.order_volume AS orders_on_detection_day
FROM core.investigation_tickets t
JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
JOIN core.dim_seller s ON s.seller_id = t.seller_id
LEFT JOIN core.fact_seller_daily_metrics m ON m.seller_id = t.seller_id AND m.metric_date = t.detected_date
ORDER BY t.priority_score DESC
LIMIT 25;
