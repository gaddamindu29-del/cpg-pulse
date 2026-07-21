"""Reference / master data generation: products, stores, retailers, DCs,
retailer<->product mapping, and the calendar dimension source.

These are generated first because every transactional dataset (sales, inventory,
shipments, promotions, e-commerce orders) references them.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import (
    CATEGORIES,
    CITIES_BY_REGION,
    CITY_COORDS,
    DISTRIBUTION_CENTERS,
    MATCH_METHODS,
    FIXED_HOLIDAYS,
    REGIONS,
    RETAILERS,
    STORE_FORMATS,
    GeneratorConfig,
)


def build_retailers() -> pd.DataFrame:
    return pd.DataFrame(RETAILERS)


def build_distribution_centers() -> pd.DataFrame:
    return pd.DataFrame(DISTRIBUTION_CENTERS)


def build_product_master(cfg: GeneratorConfig) -> pd.DataFrame:
    """Generate the internal ERP product master (the canonical product space)."""
    rng = cfg.rng("product_master")
    categories = list(CATEGORIES.keys())
    rows = []
    for i in range(cfg.num_products):
        product_id = f"P{i + 1:05d}"
        category = categories[i % len(categories)]
        meta = CATEGORIES[category]
        subcategory = rng.choice(meta["subcategories"])
        brand = rng.choice(meta["brands"])
        flavor = rng.choice(meta["flavors"])
        package_size = rng.choice(meta["package_sizes"])
        case_quantity = int(rng.choice([6, 8, 12, 24]))
        low, high = meta["unit_cost_range"]
        unit_cost = round(float(rng.uniform(low, high)), 2)

        # launch_date: spread across the ~3 years before the data window starts,
        # with a handful of "new item launch" products landing inside the window.
        days_before_start = int(rng.integers(-120, 365 * 3))
        launch_date = cfg.start_date - dt.timedelta(days=days_before_start)

        # ~8% of products are discontinued partway through the data window.
        discontinued_date = None
        if rng.random() < 0.08:
            offset = int(rng.integers(60, max(61, (cfg.end_date - cfg.start_date).days - 30)))
            discontinued_date = cfg.start_date + dt.timedelta(days=offset)

        product_name = f"{brand} {subcategory} {flavor} {package_size}".strip()
        upc = f"{rng.integers(10**10, 10**11 - 1)}"

        rows.append(
            {
                "product_id": product_id,
                "upc": upc,
                "brand": brand,
                "category": category,
                "subcategory": subcategory,
                "product_name": product_name,
                "flavor": flavor,
                "package_size": package_size,
                "case_quantity": case_quantity,
                "unit_cost": unit_cost,
                "launch_date": launch_date,
                "discontinued_date": discontinued_date,
            }
        )
    return pd.DataFrame(rows)


def build_store_master(cfg: GeneratorConfig) -> pd.DataFrame:
    rng = cfg.rng("store_master")
    rows = []
    store_seq = 1
    for retailer_id, n_stores in cfg.stores_per_retailer.items():
        fmt = STORE_FORMATS[retailer_id]
        for _ in range(n_stores):
            region = rng.choice(REGIONS)
            city, state = CITIES_BY_REGION[region][rng.integers(0, len(CITIES_BY_REGION[region]))]
            base_lat, base_lon = CITY_COORDS[city]
            # jitter so stores in the same city aren't stacked on one point
            lat = round(base_lat + rng.uniform(-0.15, 0.15), 5)
            lon = round(base_lon + rng.uniform(-0.15, 0.15), 5)

            days_before_start = int(rng.integers(0, 365 * 8))
            opening_date = cfg.start_date - dt.timedelta(days=days_before_start)

            closing_date = None
            if rng.random() < 0.03:  # ~3% of stores close mid-window
                offset = int(rng.integers(90, max(91, (cfg.end_date - cfg.start_date).days - 30)))
                closing_date = cfg.start_date + dt.timedelta(days=offset)

            store_id = f"S-{retailer_id[-3:]}-{store_seq:04d}"
            rows.append(
                {
                    "store_id": store_id,
                    "retailer_id": retailer_id,
                    "store_name": f"{fmt} #{store_seq:04d} - {city}",
                    "city": city,
                    "state": state,
                    "region": region,
                    "store_format": fmt,
                    "latitude": lat,
                    "longitude": lon,
                    "opening_date": opening_date,
                    "closing_date": closing_date,
                }
            )
            store_seq += 1
    return pd.DataFrame(rows)


def build_retailer_product_mapping(cfg: GeneratorConfig, products: pd.DataFrame, retailers: pd.DataFrame) -> pd.DataFrame:
    """Each retailer carries only a subset (assortment) of the product catalog,
    under its own retailer-specific product identifier, and the mapping to the
    canonical `product_id` can change over time (SCD2 history) -- e.g. a retailer
    re-platforms its item feed and reissues IDs, which is common in real EDI/POS
    integrations.
    """
    rng = cfg.rng("retailer_product_mapping")
    rows = []
    assortment_rate_by_retailer = {"RTL-WMT": 0.85, "RTL-TGT": 0.70, "RTL-KRG": 0.55, "RTL-AMZ": 0.95}

    for retailer_id in retailers["retailer_id"]:
        assortment_rate = assortment_rate_by_retailer.get(retailer_id, 0.75)
        carried = products[rng.random(len(products)) < assortment_rate]
        for _, prod in carried.iterrows():
            retailer_sku = f"{retailer_id[-3:]}-{rng.integers(100000, 999999)}"
            match_method = rng.choice(MATCH_METHODS, p=[0.70, 0.15, 0.10, 0.05])
            match_confidence = round(float(rng.uniform(0.97, 1.0)) if match_method == "EXACT_UPC" else float(rng.uniform(0.60, 0.96)), 3)

            effective_start = max(cfg.start_date, prod["launch_date"])
            remap_event = rng.random() < 0.06  # ~6% of retailer SKUs get remapped once mid-window

            if remap_event:
                remap_offset = int(rng.integers(60, max(61, (cfg.end_date - cfg.start_date).days - 30)))
                remap_date = cfg.start_date + dt.timedelta(days=remap_offset)
                # historical row (closed)
                rows.append(
                    {
                        "retailer_id": retailer_id,
                        "retailer_product_id": retailer_sku,
                        "retailer_product_description": f"{prod['brand']} {prod['flavor']} {prod['package_size']}".upper(),
                        "product_id": prod["product_id"],
                        "match_method": match_method,
                        "match_confidence": match_confidence,
                        "effective_start_date": effective_start,
                        "effective_end_date": remap_date - dt.timedelta(days=1),
                    }
                )
                new_sku = f"{retailer_id[-3:]}-{rng.integers(100000, 999999)}"
                rows.append(
                    {
                        "retailer_id": retailer_id,
                        "retailer_product_id": new_sku,
                        "retailer_product_description": f"{prod['brand']} {prod['flavor']} {prod['package_size']}".upper(),
                        "product_id": prod["product_id"],
                        "match_method": "RETAILER_FEED_ID",
                        "match_confidence": 1.0,
                        "effective_start_date": remap_date,
                        "effective_end_date": None,
                    }
                )
            else:
                rows.append(
                    {
                        "retailer_id": retailer_id,
                        "retailer_product_id": retailer_sku,
                        "retailer_product_description": f"{prod['brand']} {prod['flavor']} {prod['package_size']}".upper(),
                        "product_id": prod["product_id"],
                        "match_method": match_method,
                        "match_confidence": match_confidence,
                        "effective_start_date": effective_start,
                        "effective_end_date": None,
                    }
                )
    return pd.DataFrame(rows)


def _floating_holidays(year: int) -> dict[dt.date, str]:
    def nth_weekday(year_: int, month_: int, weekday_: int, n: int) -> dt.date:
        d = dt.date(year_, month_, 1)
        offset = (weekday_ - d.weekday()) % 7
        d += dt.timedelta(days=offset + 7 * (n - 1))
        return d

    def last_weekday(year_: int, month_: int, weekday_: int) -> dt.date:
        if month_ == 12:
            d = dt.date(year_ + 1, 1, 1) - dt.timedelta(days=1)
        else:
            d = dt.date(year_, month_ + 1, 1) - dt.timedelta(days=1)
        offset = (d.weekday() - weekday_) % 7
        return d - dt.timedelta(days=offset)

    memorial_day = last_weekday(year, 5, 0)  # last Monday of May
    labor_day = nth_weekday(year, 9, 0, 1)  # 1st Monday of September
    thanksgiving = nth_weekday(year, 11, 3, 4)  # 4th Thursday of November
    black_friday = thanksgiving + dt.timedelta(days=1)
    return {
        memorial_day: "Memorial Day",
        labor_day: "Labor Day",
        thanksgiving: "Thanksgiving",
        black_friday: "Black Friday",
    }


def build_calendar(cfg: GeneratorConfig) -> pd.DataFrame:
    rows = []
    for d in cfg.date_list:
        floating = _floating_holidays(d.year)
        holiday_name = FIXED_HOLIDAYS.get((d.month, d.day)) or floating.get(d)
        iso = d.isocalendar()
        rows.append(
            {
                "date": d,
                "week": int(iso.week),
                "month": d.month,
                "quarter": (d.month - 1) // 3 + 1,
                "year": d.year,
                "day_of_week": d.strftime("%A"),
                "weekend_flag": d.weekday() >= 5,
                "holiday_flag": holiday_name is not None,
                "holiday_name": holiday_name,
            }
        )
    return pd.DataFrame(rows)
