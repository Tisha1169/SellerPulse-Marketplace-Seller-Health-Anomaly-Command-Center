-- Q5: How early can we detect deterioration? (synthetic ground truth only)
-- Mean/median detection delay per anomaly type: days between injected episode
-- start_date and the first matching Ensemble flag.
WITH matches AS (
    SELECT
        g.ground_truth_id,
        g.seller_id,
        g.anomaly_type,
        g.start_date,
        min(f.flag_date) AS first_flag_date
    FROM core.ground_truth_anomalies g
    JOIN core.fact_anomaly_flags f
      ON f.seller_id = g.seller_id
     AND f.method = 'Ensemble'
     AND f.flag_date BETWEEN g.start_date AND g.end_date
     AND (f.anomaly_type = g.anomaly_type OR f.anomaly_type = 'Multi_Metric_Deterioration' OR g.anomaly_type = 'Multi_Metric_Deterioration')
    GROUP BY g.ground_truth_id, g.seller_id, g.anomaly_type, g.start_date
)
SELECT
    anomaly_type,
    count(*) AS n_detected,
    round(avg(first_flag_date - start_date), 1) AS mean_delay_days,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (first_flag_date - start_date)) AS median_delay_days,
    min(first_flag_date - start_date) AS best_case_days,
    max(first_flag_date - start_date) AS worst_case_days
FROM matches
GROUP BY anomaly_type
ORDER BY mean_delay_days;
