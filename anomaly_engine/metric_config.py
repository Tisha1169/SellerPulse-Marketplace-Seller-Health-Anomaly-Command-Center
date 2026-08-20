"""
Maps each daily metric to the anomaly_type it signals and the direction of
deterioration. Shared across every detection method so z-score, IQR, CUSUM, and
Isolation Forest all agree on what a "worsening" reading looks like for a given
metric — e.g. a rise in defect_rate is bad, a rise in avg_rating during a review
burst is a manipulation signal, not good news.
"""

# metric_name -> (anomaly_type, direction)
# direction: 'up' = deterioration is an increase, 'down' = deterioration is a
# decrease, 'both' = either direction is worth flagging.
METRIC_ANOMALY_MAP = {
    "late_shipment_rate": ("Late_Shipment_Spike", "up"),
    "defect_rate": ("Defect_Rate_Rise", "up"),
    "return_rate": ("Return_Rate_Spike", "up"),
    "review_velocity": ("Review_Velocity_Spike", "up"),
    "avg_rating": ("Rating_Manipulation", "up"),      # suspicious spike, not a genuine improvement
    "avg_price": ("Price_Anomaly", "both"),
    "order_volume": ("Order_Volume_Shock", "both"),
    "cancellation_rate": ("Multi_Metric_Deterioration", "up"),   # supporting evidence, not a standalone type
    "negative_review_rate": ("Multi_Metric_Deterioration", "up"),  # supporting evidence
    "refund_rate": ("Multi_Metric_Deterioration", "up"),           # supporting evidence
}

# Metrics whose deterioration is worth surfacing as its own standalone anomaly_type
PRIMARY_METRICS = [
    "late_shipment_rate", "defect_rate", "return_rate",
    "review_velocity", "avg_rating", "avg_price", "order_volume",
]
SUPPORTING_METRICS = ["cancellation_rate", "negative_review_rate", "refund_rate"]

SEVERITY_BANDS = [
    (6.0, "Critical"),
    (4.0, "High"),
    (2.5, "Medium"),
    (0.0, "Low"),
]


def severity_from_score(abs_score: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if abs_score >= threshold:
            return label
    return "Low"
