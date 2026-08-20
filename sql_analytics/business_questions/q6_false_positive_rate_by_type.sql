-- Q6: What percentage of flags are false positives?
-- Uses actual investigator resolutions (simulated), not the ground-truth-only
-- evaluation numbers in docs/evaluation_report.md — this reflects operational
-- outcome (how the queue actually resolved), the ground-truth version reflects
-- detection accuracy against known injected anomalies. Both are legitimate
-- "false positive rate" answers depending on which question is being asked.
SELECT
    f.anomaly_type,
    count(*) AS total_closed_tickets,
    count(*) FILTER (WHERE t.status = 'False_Positive') AS false_positives,
    round(100.0 * count(*) FILTER (WHERE t.status = 'False_Positive') / count(*), 1) AS false_positive_pct,
    count(*) FILTER (WHERE t.status = 'Resolved') AS resolved,
    count(*) FILTER (WHERE t.status = 'Escalated') AS escalated
FROM core.investigation_tickets t
JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
WHERE t.status IN ('Resolved', 'False_Positive', 'Escalated')
GROUP BY f.anomaly_type
ORDER BY false_positive_pct DESC;
