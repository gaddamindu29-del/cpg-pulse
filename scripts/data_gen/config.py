"""Run configuration and reference vocabularies for the synthetic data generator.

All "how much data" and "how much noise" knobs live here so the generator itself
stays declarative. Nothing in this module performs I/O.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class GeneratorConfig:
    """Top-level knobs for a synthetic data generation run.

    Attributes:
        seed: Master random seed. All randomness in the generator derives from
            this single value, so a given seed always reproduces byte-identical
            output (reproducibility requirement).
        start_date / end_date: Inclusive daily date range for calendar, sales,
            inventory, and shipment simulation.
        num_products: Number of SKUs in the product master.
        stores_per_retailer: Physical/virtual store count per retailer id.
        output_dir: Root directory that source subfolders are written under.
        dq_issue_rates: Probability knobs controlling injected data-quality
            problems. Kept as fractions of the relevant population so they scale
            with data volume.
    """

    seed: int = 42
    start_date: dt.date = dt.date(2025, 1, 1)
    end_date: dt.date = dt.date(2026, 6, 30)
    num_products: int = 110
    stores_per_retailer: dict[str, int] = field(
        default_factory=lambda: {
            "RTL-WMT": 40,
            "RTL-TGT": 30,
            "RTL-KRG": 25,
            "RTL-AMZ": 6,  # Amazon: regional fulfillment nodes, not storefronts
        }
    )
    output_dir: str = "data/generated"
    quarantine_sample_dir: str = "data/quarantine/_generator_preview"

    dq_issue_rates: dict[str, float] = field(
        default_factory=lambda: {
            "pos_duplicate_rate": 0.006,
            "pos_null_field_rate": 0.01,
            "pos_invalid_retailer_product_rate": 0.004,
            "pos_late_arrival_rate": 0.02,
            "inventory_null_field_rate": 0.008,
            "inventory_duplicate_rate": 0.004,
            "shipment_missing_delivery_rate": 0.05,
            "ecommerce_null_field_rate": 0.01,
            "ecommerce_duplicate_rate": 0.005,
            "price_outlier_rate": 0.0015,
            "anomaly_spike_pair_rate": 0.015,
            "anomaly_drop_pair_rate": 0.015,
            "shipment_lag_pair_rate": 0.10,
            "shipment_overship_pair_rate": 0.08,
        }
    )

    # Schema-evolution simulation: on/after this date, POS files gain a new
    # optional column and inventory files gain `reserved_units` (it is absent
    # before this date to simulate a real retailer schema change mid-history).
    schema_change_date: dt.date = dt.date(2025, 9, 1)

    def rng(self, stream_name: str) -> np.random.Generator:
        """Return an independent-but-reproducible RNG for a named stream.

        Using a distinct child RNG per logical stream (e.g. "pos_sales" vs
        "inventory") means adding/removing randomness in one part of the
        generator does not perturb unrelated streams' output, which keeps the
        seeded output stable across generator changes.

        Deliberately uses `hashlib` rather than Python's built-in `hash()`:
        `hash()` on strings is salted per-process (`PYTHONHASHSEED`) unless
        explicitly disabled, which would silently break run-to-run
        reproducibility for the exact same `--seed`.
        """
        digest = hashlib.sha256(stream_name.encode("utf-8")).digest()
        stream_seed = int.from_bytes(digest[:4], "big")
        seed_seq = np.random.SeedSequence([self.seed, stream_seed])
        return np.random.default_rng(seed_seq)

    @property
    def date_list(self) -> list[dt.date]:
        n_days = (self.end_date - self.start_date).days + 1
        return [self.start_date + dt.timedelta(days=i) for i in range(n_days)]


# ---------------------------------------------------------------------------
# Reference vocabularies (fictional CPG brand/category universe)
# ---------------------------------------------------------------------------

RETAILERS = [
    {"retailer_id": "RTL-WMT", "retailer_name": "GreatValue Mart", "retailer_type": "Mass Merchandiser"},
    {"retailer_id": "RTL-TGT", "retailer_name": "Northgate Stores", "retailer_type": "Mass Merchandiser"},
    {"retailer_id": "RTL-KRG", "retailer_name": "FreshField Grocers", "retailer_type": "Grocery"},
    {"retailer_id": "RTL-AMZ", "retailer_name": "SwiftCart Online", "retailer_type": "E-commerce Marketplace"},
]

DISTRIBUTION_CENTERS = [
    {"distribution_center_id": "DC-EAST-01", "dc_name": "Eastern Regional DC", "region": "Northeast"},
    {"distribution_center_id": "DC-SE-01", "dc_name": "Southeast Regional DC", "region": "Southeast"},
    {"distribution_center_id": "DC-MW-01", "dc_name": "Midwest Regional DC", "region": "Midwest"},
    {"distribution_center_id": "DC-SW-01", "dc_name": "Southwest Regional DC", "region": "Southwest"},
    {"distribution_center_id": "DC-WEST-01", "dc_name": "Western Regional DC", "region": "West"},
]

CATEGORIES: dict[str, dict] = {
    "Beverages": {
        "subcategories": ["Sparkling Water", "Juice", "Sports Drinks", "Ready-to-Drink Coffee"],
        "brands": ["SunCrest", "PeakRefresh"],
        "flavors": ["Original", "Citrus", "Berry", "Tropical", "Zero Sugar"],
        "package_sizes": ["12 oz Can", "16.9 oz Bottle", "1 Liter Bottle", "12-Pack Cans"],
        "unit_cost_range": (0.35, 1.80),
        "seasonality": "summer_peak",
    },
    "Snacks": {
        "subcategories": ["Salty Snacks", "Popcorn", "Granola Bars", "Trail Mix"],
        "brands": ["CrunchHouse", "GoldenBite"],
        "flavors": ["Classic Salted", "Spicy", "Sea Salt & Vinegar", "Honey Roasted", "Unflavored"],
        "package_sizes": ["1 oz Single", "8 oz Bag", "14 oz Family Bag", "6-Count Box"],
        "unit_cost_range": (0.60, 3.20),
        "seasonality": "flat",
    },
    "Breakfast & Cereal": {
        "subcategories": ["Cereal", "Oatmeal", "Breakfast Bars", "Pancake Mix"],
        "brands": ["MorningGrain", "SunriseOats"],
        "flavors": ["Original", "Cinnamon", "Honey Nut", "Berry Blend"],
        "package_sizes": ["12 oz Box", "18 oz Box", "10-Count Box"],
        "unit_cost_range": (1.10, 3.50),
        "seasonality": "winter_peak",
    },
    "Personal Care": {
        "subcategories": ["Shampoo", "Body Wash", "Deodorant", "Oral Care"],
        "brands": ["PureGlow", "DailyFresh"],
        "flavors": ["Unscented", "Lavender", "Citrus Fresh", "Mint", "Coconut"],
        "package_sizes": ["8 oz Bottle", "16 oz Bottle", "2.6 oz Stick", "4-Pack"],
        "unit_cost_range": (1.20, 4.50),
        "seasonality": "flat",
    },
    "Household": {
        "subcategories": ["Laundry Care", "Surface Cleaner", "Paper Towels", "Dish Soap"],
        "brands": ["ClearHome", "TidySpring"],
        "flavors": ["Fresh Scent", "Lemon", "Free & Clear", "Lavender"],
        "package_sizes": ["32 oz Bottle", "50 oz Bottle", "6-Roll Pack", "12-Roll Pack"],
        "unit_cost_range": (2.00, 7.50),
        "seasonality": "flat",
    },
    "Frozen Foods": {
        "subcategories": ["Frozen Entrees", "Frozen Vegetables", "Ice Cream", "Frozen Breakfast"],
        "brands": ["FrostFarm", "MorningGrain"],
        "flavors": ["Original", "Vanilla", "Chocolate", "Garden Blend"],
        "package_sizes": ["10 oz Box", "16 oz Bag", "1.5 Quart Tub"],
        "unit_cost_range": (1.50, 5.00),
        "seasonality": "summer_peak_icecream",
    },
    "Condiments & Sauces": {
        "subcategories": ["Ketchup & Mustard", "Salad Dressing", "Hot Sauce", "Pasta Sauce"],
        "brands": ["SavoryCo", "GoldenBite"],
        "flavors": ["Original", "Spicy", "Garlic Herb", "Sweet & Tangy"],
        "package_sizes": ["14 oz Bottle", "20 oz Bottle", "24 oz Jar"],
        "unit_cost_range": (1.00, 4.20),
        "seasonality": "summer_peak",
    },
}

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]

CITIES_BY_REGION = {
    "Northeast": [("Boston", "MA"), ("Newark", "NJ"), ("Albany", "NY"), ("Providence", "RI")],
    "Southeast": [("Atlanta", "GA"), ("Charlotte", "NC"), ("Orlando", "FL"), ("Nashville", "TN")],
    "Midwest": [("Chicago", "IL"), ("Columbus", "OH"), ("Milwaukee", "WI"), ("Kansas City", "MO")],
    "Southwest": [("Dallas", "TX"), ("Phoenix", "AZ"), ("Austin", "TX"), ("Albuquerque", "NM")],
    "West": [("Sacramento", "CA"), ("Portland", "OR"), ("Denver", "CO"), ("Seattle", "WA")],
}

# Approximate lat/long centroid per city, purely for a plausible map view in the
# dashboard -- not survey-accurate.
CITY_COORDS = {
    "Boston": (42.36, -71.06), "Newark": (40.74, -74.17), "Albany": (42.65, -73.75), "Providence": (41.82, -71.41),
    "Atlanta": (33.75, -84.39), "Charlotte": (35.23, -80.84), "Orlando": (28.54, -81.38), "Nashville": (36.16, -86.78),
    "Chicago": (41.88, -87.63), "Columbus": (39.96, -83.00), "Milwaukee": (43.04, -87.91), "Kansas City": (39.10, -94.58),
    "Dallas": (32.78, -96.80), "Phoenix": (33.45, -112.07), "Austin": (30.27, -97.74), "Albuquerque": (35.08, -106.65),
    "Sacramento": (38.58, -121.49), "Portland": (45.52, -122.68), "Denver": (39.74, -104.99), "Seattle": (47.61, -122.33),
}

STORE_FORMATS = {
    "RTL-WMT": "Supercenter",
    "RTL-TGT": "General Merchandise",
    "RTL-KRG": "Neighborhood Grocery",
    "RTL-AMZ": "Online Fulfillment Center",
}

SALES_CHANNELS = [
    {"channel_code": "IN_STORE", "channel_name": "In-Store", "channel_type": "Physical Retail"},
    {"channel_code": "RETAILER_ONLINE", "channel_name": "Retailer.com Pickup/Delivery", "channel_type": "Omnichannel"},
    {"channel_code": "MARKETPLACE", "channel_name": "Online Marketplace", "channel_type": "E-commerce"},
    {"channel_code": "DTC_ECOMMERCE", "channel_name": "Direct-to-Consumer", "channel_type": "E-commerce"},
]

PROMOTION_TYPES = ["Temporary Price Reduction", "Feature Ad", "Display Only", "Feature + Display", "Digital Coupon"]
DISPLAY_TYPES = ["End Cap", "Aisle Display", "Front of Store", "Digital Banner", "None"]

MATCH_METHODS = ["EXACT_UPC", "FUZZY_NAME_MATCH", "MANUAL_REVIEW", "RETAILER_FEED_ID"]

# Fixed-calendar-date holidays. Floating holidays (Memorial Day, Labor Day,
# Thanksgiving, Black Friday) are computed per-year in reference.py because
# their date moves year to year.
FIXED_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (2, 14): "Valentine's Day",
    (7, 4): "Independence Day",
    (10, 31): "Halloween",
    (12, 25): "Christmas Day",
}
