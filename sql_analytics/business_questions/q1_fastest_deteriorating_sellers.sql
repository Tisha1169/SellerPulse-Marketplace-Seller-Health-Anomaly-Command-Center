-- Q1: Which sellers are deteriorating fastest?
-- Approach: compare each seller's health score 30 days ago vs today, rank by
-- steepest decline. Uses LAG over the health score history (window function).
WITH scored AS (
    SELECT
        seller_id,
        score_date,
        health_score,
        LAG(health_score, 30) OVER (PARTITION BY seller_id ORDER BY score_date) AS health_score_30d_ago
    FROM core.seller_health_score
),
latest AS (
    SELECT DISTINCT ON (seller_id) seller_id, score_date, health_score, health_score_30d_ago
    FROM scored
    ORDER BY seller_id, score_date DESC
)
SELECT
    l.seller_id,
    s.seller_name,
    s.primary_category,
    s.seller_segment,
    l.health_score_30d_ago,
    l.health_score AS health_score_today,
    round(l.health_score - l.health_score_30d_ago, 1) AS score_change_30d
FROM latest l
JOIN core.dim_seller s ON s.seller_id = l.seller_id
WHERE l.health_score_30d_ago IS NOT NULL
ORDER BY score_change_30d ASC
LIMIT 25;
