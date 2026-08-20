-- Q7: Which categories have the highest operational risk?
-- Blends current health score distribution with open-ticket load per category.
SELECT
    s.primary_category,
    count(DISTINCT s.seller_id) AS n_sellers,
    round(avg(h.health_score), 1) AS avg_health_score,
    count(*) FILTER (WHERE h.health_tier IN ('At_Risk', 'Critical')) AS at_risk_or_critical_sellers,
    round(100.0 * count(*) FILTER (WHERE h.health_tier IN ('At_Risk', 'Critical')) / count(DISTINCT s.seller_id), 1) AS pct_at_risk_or_critical,
    (SELECT count(*) FROM core.investigation_tickets t
      JOIN core.dim_seller s2 ON s2.seller_id = t.seller_id
      WHERE s2.primary_category = s.primary_category AND t.status NOT IN ('Resolved', 'False_Positive')) AS open_tickets
FROM core.dim_seller s
JOIN core.seller_health_score h ON h.seller_id = s.seller_id AND h.score_date = (SELECT max(score_date) FROM core.seller_health_score)
GROUP BY s.primary_category
ORDER BY pct_at_risk_or_critical DESC;
