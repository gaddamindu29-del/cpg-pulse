"""Unit tests for the synthetic data generator (Phase 2).

Run with: pytest tests/unit/test_generator.py -v

These tests intentionally use a small configuration (few products/stores, short
date range) so the whole suite runs in a few seconds -- the generator's own
runtime scaling is exercised manually (see docs/runbook.md), not in CI.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from data_gen import ecommerce, pricing, promotions as promo_mod, quality_issues, reference, simulate, writers
from data_gen.config import GeneratorConfig


@pytest.fixture(scope="module")
def small_cfg() -> GeneratorConfig:
    return GeneratorConfig(
        seed=123,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 3, 31),  # spans the schema_change_date below
        num_products=14,
        stores_per_retailer={"RTL-WMT": 4, "RTL-TGT": 3, "RTL-KRG": 3, "RTL-AMZ": 2},
        schema_change_date=dt.date(2025, 2, 15),
    )


@pytest.fixture(scope="module")
def built(small_cfg: GeneratorConfig) -> dict:
    retailers = reference.build_retailers()
    dcs = reference.build_distribution_centers()
    products = reference.build_product_master(small_cfg)
    stores = reference.build_store_master(small_cfg)
    mapping = reference.build_retailer_product_mapping(small_cfg, products, retailers)
    calendar = reference.build_calendar(small_cfg)
    price_table = pricing.build_regular_price_table(small_cfg, mapping, products)
    promotions = promo_mod.build_promotions(small_cfg, mapping, price_table)
    sim = simulate.simulate_transactions(small_cfg, retailers, stores, products, mapping, price_table, promotions)
    orders = ecommerce.build_ecommerce_orders(small_cfg, products)
    return {
        "retailers": retailers,
        "dcs": dcs,
        "products": products,
        "stores": stores,
        "mapping": mapping,
        "calendar": calendar,
        "price_table": price_table,
        "promotions": promotions,
        "pos_sales": sim["pos_sales"],
        "inventory": sim["inventory_snapshots"],
        "shipments": sim["shipments"],
        "orders": orders,
    }


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

class TestReferenceData:
    def test_product_master_row_count_matches_config(self, small_cfg, built):
        assert len(built["products"]) == small_cfg.num_products

    def test_product_master_unique_ids(self, built):
        assert built["products"]["product_id"].is_unique

    def test_store_master_row_count_matches_config(self, small_cfg, built):
        expected = sum(small_cfg.stores_per_retailer.values())
        assert len(built["stores"]) == expected

    def test_store_master_unique_ids(self, built):
        assert built["stores"]["store_id"].is_unique

    def test_every_store_retailer_id_is_valid(self, built):
        valid_retailers = set(built["retailers"]["retailer_id"])
        assert set(built["stores"]["retailer_id"]).issubset(valid_retailers)

    def test_mapping_product_ids_are_valid(self, built):
        valid_products = set(built["products"]["product_id"])
        assert set(built["mapping"]["product_id"]).issubset(valid_products)

    def test_mapping_scd2_no_overlapping_effective_ranges(self, built):
        mapping = built["mapping"]
        for (retailer_id, retailer_product_id), grp in mapping.groupby(["retailer_id", "retailer_product_id"]):
            grp = grp.sort_values("effective_start_date")
            ends = grp["effective_end_date"].tolist()
            starts = grp["effective_start_date"].tolist()
            for i in range(len(grp) - 1):
                assert ends[i] is not None and not pd.isna(ends[i]), "non-final segment must be closed"
                assert ends[i] < starts[i + 1]

    def test_calendar_covers_full_date_range_with_no_gaps(self, small_cfg, built):
        calendar = built["calendar"]
        expected_days = (small_cfg.end_date - small_cfg.start_date).days + 1
        assert len(calendar) == expected_days
        assert calendar["date"].is_unique

    def test_calendar_quarter_and_weekend_flag_correct(self, built):
        calendar = built["calendar"].set_index("date")
        jan_1_2025 = calendar.loc[dt.date(2025, 1, 1)]
        assert jan_1_2025["quarter"] == 1
        assert jan_1_2025["holiday_flag"] == True  # noqa: E712 (New Year's Day)
        saturday = calendar[calendar["day_of_week"] == "Saturday"].iloc[0]
        assert bool(saturday["weekend_flag"]) is True


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------

class TestPromotions:
    def test_start_before_end(self, built):
        promos = built["promotions"]
        assert (promos["start_date"] <= promos["end_date"]).all()

    def test_promotional_price_below_regular_price(self, built):
        promos = built["promotions"]
        assert (promos["promotional_price"] < promos["regular_price"]).all()

    def test_discount_percentage_matches_prices(self, built):
        promos = built["promotions"]
        implied = (1 - promos["promotional_price"] / promos["regular_price"]) * 100
        assert (abs(implied - promos["discount_percentage"]) < 0.6).all()

    def test_public_columns_exclude_internal_lift_factor(self, built):
        public_cols = set(built["promotions"][promo_mod.PUBLIC_PROMOTION_COLUMNS].columns)
        assert "true_lift_factor_internal" not in public_cols


# ---------------------------------------------------------------------------
# Transactional simulation (pre data-quality injection == "clean" data)
# ---------------------------------------------------------------------------

class TestSimulation:
    def test_pos_units_sold_positive(self, built):
        assert (built["pos_sales"]["units_sold"] > 0).all()

    def test_pos_net_sales_not_greater_than_gross(self, built):
        pos = built["pos_sales"]
        assert (pos["net_sales"] <= pos["gross_sales"] + 1e-6).all()

    def test_pos_retailer_product_ids_resolve_to_mapping(self, built):
        pos = built["pos_sales"]
        mapping = built["mapping"]
        valid_pairs = set(zip(mapping["retailer_id"], mapping["retailer_product_id"]))
        observed_pairs = set(zip(pos["retailer_id"], pos["retailer_product_id"]))
        # every clean (pre-DQ-injection) POS row must reference a real mapping entry
        assert observed_pairs.issubset(valid_pairs)

    def test_inventory_available_never_negative(self, built):
        assert (built["inventory"]["available_units"] >= 0).all()

    def test_inventory_on_hand_never_negative(self, built):
        assert (built["inventory"]["on_hand_units"] >= 0).all()

    def test_shipments_have_valid_status(self, built):
        valid = {"DELIVERED", "IN_TRANSIT", "DELAYED", "CANCELLED"}
        assert set(built["shipments"]["shipment_status"]).issubset(valid)

    def test_shipments_units_positive(self, built):
        assert (built["shipments"]["units_shipped"] > 0).all()

    def test_stockout_events_exist(self, built):
        """The replenishment-lag injection should produce at least some
        available_units == 0 rows across a run this size -- otherwise the
        stockout-risk analytics built in later phases would have nothing to
        detect."""
        assert (built["inventory"]["available_units"] == 0).any()

    def test_ecommerce_net_sales_non_negative(self, built):
        assert (built["orders"]["net_sales"] >= 0).all()

    def test_ecommerce_return_flag_matches_status(self, built):
        orders = built["orders"]
        returned = orders[orders["order_status"] == "RETURNED"]
        assert returned["return_flag"].all()


# ---------------------------------------------------------------------------
# Data-quality issue injection
# ---------------------------------------------------------------------------

class TestQualityIssueInjection:
    def test_duplicates_increase_row_count(self, small_cfg, built):
        original_len = len(built["pos_sales"])
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        assert len(with_issues) > original_len

    def test_invalid_retailer_product_ids_are_injected(self, small_cfg, built):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        assert with_issues["retailer_product_id"].str.startswith("UNKNOWN-").any()

    def test_nulls_are_injected(self, small_cfg, built):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        assert with_issues["discount_amount"].isna().any() or with_issues["sales_channel"].isna().any()

    def test_late_arrivals_exist(self, small_cfg, built):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        lag_days = (with_issues["_extract_date"] - with_issues["transaction_date"]).apply(lambda td: td.days)
        assert (lag_days > 4).any()

    def test_price_outliers_exist(self, small_cfg, built):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        assert (with_issues["selling_price"] > with_issues["regular_price"] * 5).any()

    def test_inventory_schema_evolution_renames_column(self, small_cfg, built):
        with_issues = quality_issues.inject_inventory_issues(small_cfg, built["inventory"])
        pre, post = quality_issues.apply_inventory_schema_evolution(small_cfg, with_issues)
        assert "reserved_qty" in pre.columns and "reserved_units" not in pre.columns
        assert "reserved_units" in post.columns and "reserved_qty" not in post.columns
        assert (pre["snapshot_date"] < small_cfg.schema_change_date).all()
        assert (post["snapshot_date"] >= small_cfg.schema_change_date).all()

    def test_pos_schema_evolution_adds_compatible_column(self, small_cfg, built):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        pre, post = quality_issues.apply_pos_schema_evolution(small_cfg, with_issues)
        assert "promo_flag" not in pre.columns
        assert "promo_flag" in post.columns


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_produces_identical_product_master(self, small_cfg):
        p1 = reference.build_product_master(small_cfg)
        p2 = reference.build_product_master(small_cfg)
        pd.testing.assert_frame_equal(p1, p2)

    def test_same_seed_produces_identical_store_master(self, small_cfg):
        s1 = reference.build_store_master(small_cfg)
        s2 = reference.build_store_master(small_cfg)
        pd.testing.assert_frame_equal(s1, s2)

    def test_different_seed_produces_different_output(self, small_cfg):
        cfg_a = small_cfg
        cfg_b = GeneratorConfig(
            seed=999,
            start_date=small_cfg.start_date,
            end_date=small_cfg.end_date,
            num_products=small_cfg.num_products,
            stores_per_retailer=small_cfg.stores_per_retailer,
        )
        p1 = reference.build_product_master(cfg_a)
        p2 = reference.build_product_master(cfg_b)
        assert not p1["unit_cost"].equals(p2["unit_cost"])

    def test_rng_stream_seed_independent_of_python_hash_randomization(self, small_cfg):
        """Regression test for a real bug caught during development: the
        original implementation used Python's built-in hash() to derive
        per-stream seeds, which is salted per-process (PYTHONHASHSEED) and
        silently broke cross-run reproducibility despite a fixed --seed.
        cfg.rng() must use a deterministic hash (hashlib) instead.
        """
        r1 = small_cfg.rng("some_stream_name").integers(0, 1_000_000, size=10)
        r2 = small_cfg.rng("some_stream_name").integers(0, 1_000_000, size=10)
        assert (r1 == r2).all()


# ---------------------------------------------------------------------------
# Writers (multi-format output)
# ---------------------------------------------------------------------------

class TestWriters:
    def test_reference_dataset_round_trips_all_formats(self, built, tmp_path):
        out_dir = tmp_path / "out"
        writers.write_reference_dataset(built["products"], "product_master", str(out_dir), formats=("csv", "json", "parquet"))

        csv_df = pd.read_csv(out_dir / "product_master" / "csv" / "product_master.csv")
        json_df = pd.read_json(out_dir / "product_master" / "json" / "product_master.json")
        parquet_df = pd.read_parquet(out_dir / "product_master" / "parquet" / "product_master.parquet")

        assert len(csv_df) == len(built["products"])
        assert len(json_df) == len(built["products"])
        assert len(parquet_df) == len(built["products"])

    def test_partitioned_dataset_requires_extract_date_column(self, built, tmp_path):
        with pytest.raises(ValueError):
            writers.write_partitioned_dataset(built["pos_sales"], "retail_pos_sales", str(tmp_path), formats=("csv",))

    def test_partitioned_dataset_drops_extract_date_from_payload(self, small_cfg, built, tmp_path):
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        pre, post = quality_issues.apply_pos_schema_evolution(small_cfg, with_issues)
        writers.write_partitioned_dataset(pre, "retail_pos_sales", str(tmp_path), formats=("csv",), file_suffix="_a")
        files = list((tmp_path / "retail_pos_sales" / "csv").rglob("*.csv"))
        assert len(files) > 0
        sample = pd.read_csv(files[0])
        assert "_extract_date" not in sample.columns

    def test_pre_and_post_generations_do_not_collide_on_shared_extract_dates(self, small_cfg, built, tmp_path):
        """Both schema-evolution generations can produce a file for the same
        extract_date (e.g. a late-arriving pre-change record). Without
        file_suffix disambiguation, the second write silently clobbers the
        first -- this test guards that regression."""
        with_issues = quality_issues.inject_pos_issues(small_cfg, built["pos_sales"], built["mapping"])
        pre, post = quality_issues.apply_pos_schema_evolution(small_cfg, with_issues)
        pre_rows = writers.write_partitioned_dataset(pre, "retail_pos_sales", str(tmp_path), formats=("csv",), file_suffix="_a")
        post_rows = writers.write_partitioned_dataset(post, "retail_pos_sales", str(tmp_path), formats=("csv",), file_suffix="_b")
        all_files = {p.name for p in pre_rows} | {p.name for p in post_rows}
        assert len(all_files) == len(pre_rows) + len(post_rows)
