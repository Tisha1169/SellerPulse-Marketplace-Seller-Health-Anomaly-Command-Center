"""
Central configuration for synthetic data generation.

All distribution parameters live here so the generator is reproducible (fixed seed)
and so scale can be tuned without touching generation logic. Distributions are chosen
to mimic real marketplace shape, not uniform randomness:
  - seller order volume: power-law-ish (few power sellers, many small ones)
  - seller tenure: right-skewed toward newer sellers, long tail of veterans
  - category mix: a handful of categories carry most GMV
  - ratings: left-skewed toward positive (most e-commerce reviews are 4-5 stars)
"""
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

RANDOM_SEED = int(os.getenv("RANDOM_SEED", 42))

# ------------------------------------------------------------------
# Scale presets — keeps the generator laptop-friendly by default while
# leaving a path to "full" scale for a beefier machine.
# ------------------------------------------------------------------
SCALE_PRESETS = {
    "small": dict(n_sellers=300, n_products=3_000, n_customers=8_000, n_days=180),
    "medium": dict(n_sellers=2_000, n_products=20_000, n_customers=50_000, n_days=365),
    "full": dict(n_sellers=6_000, n_products=60_000, n_customers=200_000, n_days=540),
}
DATA_SCALE = os.getenv("DATA_SCALE", "medium")
SCALE = SCALE_PRESETS[DATA_SCALE]

N_SELLERS = SCALE["n_sellers"]
N_PRODUCTS = SCALE["n_products"]
N_CUSTOMERS = SCALE["n_customers"]
N_DAYS = SCALE["n_days"]

SIMULATION_END_DATE = date(2026, 8, 20)  # "today" in the simulated timeline

# ------------------------------------------------------------------
# Category taxonomy — weighted so a handful of categories dominate GMV,
# matching real marketplace concentration.
# ------------------------------------------------------------------
CATEGORIES = {
    "Electronics": 0.18,
    "Home & Kitchen": 0.15,
    "Apparel & Fashion": 0.14,
    "Beauty & Personal Care": 0.10,
    "Sports & Outdoors": 0.08,
    "Toys & Games": 0.07,
    "Grocery & Gourmet": 0.07,
    "Books & Media": 0.06,
    "Automotive": 0.05,
    "Health & Household": 0.05,
    "Office & Stationery": 0.03,
    "Pet Supplies": 0.02,
}
SUBCATEGORIES = {
    "Electronics": ["Mobile Accessories", "Audio", "Computer Peripherals", "Smart Home", "Cameras"],
    "Home & Kitchen": ["Cookware", "Furniture", "Decor", "Storage", "Small Appliances"],
    "Apparel & Fashion": ["Men's Wear", "Women's Wear", "Footwear", "Accessories", "Kids Wear"],
    "Beauty & Personal Care": ["Skincare", "Haircare", "Makeup", "Fragrance", "Grooming"],
    "Sports & Outdoors": ["Fitness Equipment", "Outdoor Gear", "Cycling", "Team Sports", "Yoga"],
    "Toys & Games": ["Educational Toys", "Action Figures", "Board Games", "Puzzles", "Outdoor Toys"],
    "Grocery & Gourmet": ["Snacks", "Beverages", "Pantry Staples", "Organic", "Gourmet Foods"],
    "Books & Media": ["Fiction", "Non-Fiction", "Children's Books", "Comics", "Educational"],
    "Automotive": ["Car Accessories", "Tools", "Care Products", "Electronics", "Tires & Wheels"],
    "Health & Household": ["Vitamins", "Cleaning Supplies", "Personal Care", "Medical Supplies", "Paper Products"],
    "Office & Stationery": ["Writing Instruments", "Paper Products", "Organizers", "Printers", "Desk Accessories"],
    "Pet Supplies": ["Dog", "Cat", "Fish & Aquatic", "Bird", "Small Animal"],
}

# ------------------------------------------------------------------
# Seller segment distribution (by order-volume tier) — power-law shaped.
# Micro sellers are numerous but low volume; Power sellers are few but huge.
# ------------------------------------------------------------------
SELLER_SEGMENT_WEIGHTS = {"Micro": 0.50, "Small": 0.30, "Mid": 0.15, "Power": 0.05}
SELLER_SEGMENT_DAILY_ORDER_LAMBDA = {"Micro": 0.7, "Small": 3.0, "Mid": 12.0, "Power": 55.0}

SELLER_TENURE_COHORT_WEIGHTS = {"New": 0.25, "Growing": 0.30, "Established": 0.30, "Veteran": 0.15}
TENURE_COHORT_DAYS_RANGE = {
    "New": (0, 180),
    "Growing": (181, 730),
    "Established": (731, 1825),
    "Veteran": (1826, 4380),
}

BUSINESS_TYPE_WEIGHTS = {"Individual": 0.35, "LLC": 0.45, "Corporation": 0.20}
FULFILLMENT_TYPE_WEIGHTS = {"Marketplace-Fulfilled": 0.55, "Self-Ship": 0.45}

COUNTRIES_REGIONS = {
    "USA": ["Northeast", "Midwest", "South", "West"],
    "India": ["North", "South", "East", "West"],
    "UK": ["England", "Scotland", "Wales", "Northern Ireland"],
    "Canada": ["Ontario", "Quebec", "British Columbia", "Alberta"],
}
COUNTRY_WEIGHTS = {"USA": 0.45, "India": 0.30, "UK": 0.15, "Canada": 0.10}

PRICE_TIER_WEIGHTS = {"Budget": 0.45, "Mid": 0.40, "Premium": 0.15}
PRICE_TIER_RANGE = {"Budget": (5, 30), "Mid": (30, 120), "Premium": (120, 800)}

CUSTOMER_SEGMENT_WEIGHTS = {"New": 0.30, "Occasional": 0.40, "Frequent": 0.22, "VIP": 0.08}

# ------------------------------------------------------------------
# Baseline operational rates (healthy-seller norms) — anomaly injection
# perturbs a subset of sellers away from these baselines.
# ------------------------------------------------------------------
BASELINE_RATES = {
    "late_shipment_rate": 0.045,
    "cancellation_rate": 0.025,
    "return_rate": 0.06,
    "defect_related_return_share": 0.35,   # share of returns that are defect-coded
    "review_rate_per_order": 0.12,          # probability an order generates a review
    "avg_rating_mean": 4.3,
    "avg_rating_std": 0.6,
}

# Segment-level baseline multipliers (Power sellers run tighter ops than Micro)
SEGMENT_QUALITY_MULTIPLIER = {"Power": 0.6, "Mid": 0.85, "Small": 1.0, "Micro": 1.35}

# ------------------------------------------------------------------
# Anomaly injection — sellers and episode parameters
# ------------------------------------------------------------------
PCT_SELLERS_WITH_INJECTED_ANOMALY = 0.08  # ~8% of sellers get a labeled deterioration episode
ANOMALY_EPISODE_LENGTH_RANGE = (10, 35)   # days
ANOMALY_TYPES = [
    "Late_Shipment_Spike",
    "Defect_Rate_Rise",
    "Return_Rate_Spike",
    "Review_Velocity_Spike",
    "Rating_Manipulation",
    "Price_Anomaly",
    "Order_Volume_Shock",
    "Multi_Metric_Deterioration",
]
ANOMALY_TYPE_WEIGHTS = {
    "Late_Shipment_Spike": 0.18,
    "Defect_Rate_Rise": 0.16,
    "Return_Rate_Spike": 0.14,
    "Review_Velocity_Spike": 0.12,
    "Rating_Manipulation": 0.10,
    "Price_Anomaly": 0.10,
    "Order_Volume_Shock": 0.10,
    "Multi_Metric_Deterioration": 0.10,
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
