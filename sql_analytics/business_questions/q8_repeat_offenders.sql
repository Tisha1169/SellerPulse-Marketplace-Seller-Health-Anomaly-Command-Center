-- Q8: Which sellers repeatedly trigger alerts?
-- Cohort analysis: sellers with the most distinct investigation cases, and how
-- many were NOT false positives (i.e. repeated genuine issues, not repeated noise).
SELECT
    t.seller_id,
    s.seller_name,
    s.seller_segment,
    count(*) AS total_tickets,
    count(*) FILTER (WHERE t.status = 'False_Positive') AS false_positive_tickets,
    count(*) FILTER (WHERE t.status != 'False_Positive') AS genuine_tickets,
    count(DISTINCT f.anomaly_type) AS distinct_anomaly_types,
    min(t.detected_date) AS first_flagged,
    max(t.detected_date) AS most_recent_flagged
FROM core.investigation_tickets t
JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
JOIN core.dim_seller s ON s.seller_id = t.seller_id
GROUP BY t.seller_id, s.seller_name, s.seller_segment
HAVING count(*) >= 3
ORDER BY genuine_tickets DESC, total_tickets DESC
LIMIT 25;
