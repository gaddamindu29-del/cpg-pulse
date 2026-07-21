"""Direct-to-consumer e-commerce order generation.

Unlike retail POS (which flows through a retailer + physical/virtual store),
DTC orders are CPG Pulse's own web store: one product, one customer, one order
line, with its own price and fulfillment/return behavior. This is intentionally
decoupled from the retailer inventory simulation in simulate.py -- in a real
company these genuinely are separate systems (retailer EDI feeds vs. an
internal Shopify/Salesforce Commerce order database).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import GeneratorConfig

ORDER_STATUSES = ["DELIVERED", "SHIPPED", "PROCESSING", "CANCELLED", "RETURNED"]
ORDER_STATUS_WEIGHTS = [0.72, 0.10, 0.05, 0.05, 0.08]
FULFILLMENT_TYPES = ["STANDARD_SHIP", "EXPEDITED_SHIP", "SUBSCRIBE_AND_SAVE"]


def build_ecommerce_orders(cfg: GeneratorConfig, products: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("ecommerce")
    n_customers = max(500, cfg.num_products * 40)
    customer_pool = [f"CUST-{i:07d}" for i in range(1, n_customers + 1)]

    # DTC prices are typically close to MSRP; derive a stable per-product DTC
    # price from unit_cost with a flat manufacturer-direct markup.
    dtc_price = {
        row.product_id: round(max(0.99, row.unit_cost * 2.1) - 0.01, 2) for row in products.itertuples()
    }
    product_popularity_dtc = {
        row.product_id: float(rng.lognormal(mean=0.0, sigma=0.7)) for row in products.itertuples()
    }

    dates = cfg.date_list
    rows = []
    order_seq = 1
    for d in dates:
        # site-wide baseline order volume with mild weekday/weekend + growth trend
        day_index = (d - cfg.start_date).days
        growth = 1.0 + 0.15 * (day_index / max(1, (cfg.end_date - cfg.start_date).days))  # gradual DTC channel growth
        weekend_boost = 1.2 if d.weekday() >= 5 else 1.0
        site_wide_discount_day = rng.random() < 0.05  # ~monthly site-wide promo day

        for row in products.itertuples():
            if row.launch_date > d:
                continue
            if row.discontinued_date is not None and not pd.isna(row.discontinued_date) and d >= row.discontinued_date:
                continue
            lam = 0.35 * product_popularity_dtc[row.product_id] * growth * weekend_boost
            n_orders_today = rng.poisson(max(lam, 0.001))
            if n_orders_today <= 0:
                continue
            for _ in range(int(n_orders_today)):
                units = int(rng.choice([1, 1, 1, 2, 2, 3], p=[0.35, 0.2, 0.15, 0.15, 0.1, 0.05]))
                unit_price = dtc_price[row.product_id]
                discount_amount = 0.0
                if site_wide_discount_day:
                    discount_amount = round(unit_price * units * rng.uniform(0.1, 0.25), 2)
                elif rng.random() < 0.08:
                    discount_amount = round(unit_price * units * rng.uniform(0.05, 0.15), 2)
                gross = round(unit_price * units, 2)
                net_sales = round(max(gross - discount_amount, 0.0), 2)
                status = rng.choice(ORDER_STATUSES, p=ORDER_STATUS_WEIGHTS)
                return_flag = status == "RETURNED"
                fulfillment = rng.choice(FULFILLMENT_TYPES, p=[0.65, 0.20, 0.15])

                rows.append(
                    {
                        "order_id": f"ORD-{order_seq:08d}",
                        "order_date": d,
                        "customer_id": customer_pool[rng.integers(0, n_customers)],
                        "product_id": row.product_id,
                        "units_ordered": units,
                        "unit_price": unit_price,
                        "discount_amount": discount_amount,
                        "net_sales": net_sales,
                        "order_status": status,
                        "fulfillment_type": fulfillment,
                        "return_flag": bool(return_flag),
                    }
                )
                order_seq += 1

    return pd.DataFrame(rows)
