"""Generate dim_seller with realistic segment, tenure, and category distributions."""
import numpy as np
import pandas as pd
from faker import Faker

from data_generator import config as cfg

fake = Faker()
Faker.seed(cfg.RANDOM_SEED)
rng = np.random.default_rng(cfg.RANDOM_SEED)


def _weighted_choice(weights_dict: dict, n: int) -> np.ndarray:
    keys = list(weights_dict.keys())
    probs = np.array(list(weights_dict.values()))
    probs = probs / probs.sum()
    return rng.choice(keys, size=n, p=probs)


def generate_sellers(n_sellers: int = cfg.N_SELLERS) -> pd.DataFrame:
    seller_id = np.arange(1, n_sellers + 1)
    seller_segment = _weighted_choice(cfg.SELLER_SEGMENT_WEIGHTS, n_sellers)
    tenure_cohort = _weighted_choice(cfg.SELLER_TENURE_COHORT_WEIGHTS, n_sellers)
    business_type = _weighted_choice(cfg.BUSINESS_TYPE_WEIGHTS, n_sellers)
    fulfillment_type = _weighted_choice(cfg.FULFILLMENT_TYPE_WEIGHTS, n_sellers)
    primary_category = _weighted_choice(cfg.CATEGORIES, n_sellers)
    country = _weighted_choice(cfg.COUNTRY_WEIGHTS, n_sellers)
    region = [rng.choice(cfg.COUNTRIES_REGIONS[c]) for c in country]

    tenure_days = np.array(
        [rng.integers(*cfg.TENURE_COHORT_DAYS_RANGE[t]) for t in tenure_cohort]
    )
    signup_date = [
        cfg.SIMULATION_END_DATE - pd.Timedelta(days=int(d)) for d in tenure_days
    ]

    seller_name = [fake.unique.company() for _ in range(n_sellers)]

    df = pd.DataFrame(
        {
            "seller_id": seller_id,
            "seller_name": seller_name,
            "signup_date": signup_date,
            "tenure_cohort": tenure_cohort,
            "seller_segment": seller_segment,
            "primary_category": primary_category,
            "business_type": business_type,
            "fulfillment_type": fulfillment_type,
            "country": country,
            "region": region,
            "is_active": True,
            "effective_start_date": signup_date,
            "effective_end_date": None,
            "is_current": True,
        }
    )
    return df


if __name__ == "__main__":
    import os

    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    df = generate_sellers()
    df.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_seller.csv"), index=False)
    print(f"Generated {len(df)} sellers -> {cfg.OUTPUT_DIR}/dim_seller.csv")
    print(df["seller_segment"].value_counts(normalize=True))
