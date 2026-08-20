"""Generate dim_product, distributed across sellers proportional to segment size
(Power sellers list far more SKUs than Micro sellers)."""
import numpy as np
import pandas as pd
from faker import Faker

from data_generator import config as cfg

fake = Faker()
Faker.seed(cfg.RANDOM_SEED + 1)
rng = np.random.default_rng(cfg.RANDOM_SEED + 1)

SEGMENT_SKU_WEIGHT = {"Micro": 1, "Small": 4, "Mid": 15, "Power": 60}


def generate_products(sellers_df: pd.DataFrame, n_products: int = cfg.N_PRODUCTS) -> pd.DataFrame:
    weights = sellers_df["seller_segment"].map(SEGMENT_SKU_WEIGHT).to_numpy(dtype=float)
    weights = weights / weights.sum()
    seller_ids_for_products = rng.choice(sellers_df["seller_id"].to_numpy(), size=n_products, p=weights)

    seller_category_map = sellers_df.set_index("seller_id")["primary_category"].to_dict()
    seller_signup_map = sellers_df.set_index("seller_id")["signup_date"].to_dict()

    product_id = np.arange(1, n_products + 1)
    category = [seller_category_map[sid] for sid in seller_ids_for_products]
    subcategory = [rng.choice(cfg.SUBCATEGORIES[c]) for c in category]
    price_tier = [rng.choice(list(cfg.PRICE_TIER_WEIGHTS.keys()), p=list(cfg.PRICE_TIER_WEIGHTS.values())) for _ in range(n_products)]
    list_price = [
        round(rng.uniform(*cfg.PRICE_TIER_RANGE[t]), 2) for t in price_tier
    ]

    launch_date = []
    for sid in seller_ids_for_products:
        seller_signup = seller_signup_map[sid]
        days_since_signup = (cfg.SIMULATION_END_DATE - seller_signup).days
        offset = int(rng.integers(0, max(days_since_signup, 1)))
        launch_date.append(seller_signup + pd.Timedelta(days=offset))

    product_name = [f"{fake.word().capitalize()} {sc}" for sc in subcategory]

    df = pd.DataFrame(
        {
            "product_id": product_id,
            "seller_id": seller_ids_for_products,
            "product_name": product_name,
            "category": category,
            "subcategory": subcategory,
            "price_tier": price_tier,
            "list_price": list_price,
            "launch_date": launch_date,
            "is_active": True,
        }
    )
    return df


if __name__ == "__main__":
    import os

    sellers_df = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "dim_seller.csv"), parse_dates=["signup_date"])
    sellers_df["signup_date"] = sellers_df["signup_date"].dt.date
    df = generate_products(sellers_df)
    df.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_product.csv"), index=False)
    print(f"Generated {len(df)} products -> {cfg.OUTPUT_DIR}/dim_product.csv")
