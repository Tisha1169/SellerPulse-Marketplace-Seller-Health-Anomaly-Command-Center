-- Q9: Investigator workload and SLA performance (supports "how much effort could
-- early detection save" business-impact framing, and basic ops capacity planning).
SELECT
    assigned_investigator,
    count(*) AS total_cases,
    count(*) FILTER (WHERE status NOT IN ('Resolved', 'False_Positive', 'Escalated')) AS open_cases,
    count(*) FILTER (WHERE is_sla_breached) AS sla_breaches,
    round(100.0 * count(*) FILTER (WHERE is_sla_breached) / count(*), 1) AS sla_breach_pct,
    round(avg(EXTRACT(EPOCH FROM (resolved_at - detected_date)) / 3600), 1) AS avg_resolution_hours
FROM core.investigation_tickets
GROUP BY assigned_investigator
ORDER BY total_cases DESC;
