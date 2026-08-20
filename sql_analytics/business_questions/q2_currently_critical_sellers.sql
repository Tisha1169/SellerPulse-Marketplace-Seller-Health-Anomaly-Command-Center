-- Q2: Which sellers are currently critical?
SELECT
    h.seller_id,
    s.seller_name,
    s.primary_category,
    s.seller_segment,
    h.health_score,
    h.health_tier,
    h.defect_component,
    h.late_shipment_component,
    h.return_component,
    h.review_component,
    (SELECT count(*) FROM core.investigation_tickets t
      WHERE t.seller_id = h.seller_id AND t.status NOT IN ('Resolved', 'False_Positive')) AS open_tickets
FROM core.seller_health_score h
JOIN core.dim_seller s ON s.seller_id = h.seller_id
WHERE h.score_date = (SELECT max(score_date) FROM core.seller_health_score)
  AND h.health_tier = 'Critical'
ORDER BY h.health_score ASC;
