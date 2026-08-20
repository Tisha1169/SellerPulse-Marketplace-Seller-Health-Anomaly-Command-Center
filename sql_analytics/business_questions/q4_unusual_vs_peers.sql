-- Q4: Which sellers are unusual relative to their peers (not just their own history)?
-- Uses the peer-cohort baseline table directly — sellers with the largest average
-- |cohort_zscore| across defect/return/late-shipment rates over the trailing 30 days.
SELECT
    b.seller_id,
    s.seller_name,
    s.tenure_cohort,
    s.primary_category,
    s.seller_segment,
    round(avg(abs(b.cohort_zscore)), 2) AS avg_abs_cohort_zscore_30d,
    count(*) FILTER (WHERE abs(b.cohort_zscore) >= 2.5) AS days_flagged_vs_peers
FROM core.seller_metric_cohort_baseline b
JOIN core.dim_seller s ON s.seller_id = b.seller_id
WHERE b.metric_name IN ('defect_rate', 'late_shipment_rate', 'return_rate')
  AND b.metric_date >= (SELECT max(metric_date) - 30 FROM core.fact_seller_daily_metrics)
  AND b.cohort_zscore IS NOT NULL
GROUP BY b.seller_id, s.seller_name, s.tenure_cohort, s.primary_category, s.seller_segment
HAVING count(*) >= 10
ORDER BY avg_abs_cohort_zscore_30d DESC
LIMIT 25;
