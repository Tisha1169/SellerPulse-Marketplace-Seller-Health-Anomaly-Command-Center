-- Q10: Which cases should an operations investigator handle first, right now?
-- This is the literal query behind the "Investigation Command Center" dashboard
-- view: open tickets ranked by priority score, with SLA countdown.
SELECT
    t.case_id,
    t.seller_id,
    s.seller_name,
    f.anomaly_type,
    f.affected_metric,
    t.severity,
    t.priority_score,
    t.status,
    t.assigned_investigator,
    t.sla_deadline,
    EXTRACT(EPOCH FROM (t.sla_deadline - now())) / 3600 AS hours_until_sla_deadline,
    CASE
        WHEN t.is_sla_breached THEN 'BREACHED'
        WHEN t.sla_deadline - now() < interval '24 hours' THEN 'URGENT'
        ELSE 'ON_TRACK'
    END AS sla_status,
    f.explanation
FROM core.investigation_tickets t
JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
JOIN core.dim_seller s ON s.seller_id = t.seller_id
WHERE t.status NOT IN ('Resolved', 'False_Positive')
ORDER BY t.priority_score DESC
LIMIT 50;
