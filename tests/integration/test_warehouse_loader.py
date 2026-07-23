"""Integration tests for scripts/load_to_warehouse.py's fallback-standardize
path (duplicate-record dedup, invalid-product-mapping handling), plus SQL-level
assertions against a real, dbt-built warehouse confirming the same guarantees
hold end-to-end through staging.

Run: pytest tests/integration/test_warehouse_loader.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from load_to_warehouse import _fallback_standardize, _read_any_format  # noqa: E402

from tests.conftest import SAMPLE_DIR, require_sample_data  # noqa: E402


@pytest.fixture(scope="module")
def sample_pos_and_mapping():
    require_sample_data()
    raw_pos = _read_any_format(SAMPLE_DIR / "retail_pos_sales")
    mapping = _read_any_format(SAMPLE_DIR / "retailer_product_mapping")
    return raw_pos, mapping


class TestDuplicateRecordHandling:
    def test_generator_actually_injected_duplicates(self, sample_pos_and_mapping):
        """Sanity check on the fixture itself: scripts/data_gen/quality_issues.py
        injects exact-duplicate rows (pos_duplicate_rate) -- if this ever stops
        being true, the dedup test below would pass vacuously."""
        raw_pos, _ = sample_pos_and_mapping
        key_cols = ["retailer_id", "store_id", "retailer_product_id", "transaction_date", "sales_channel"]
        dup_count = len(raw_pos) - len(raw_pos.drop_duplicates(subset=key_cols))
        assert dup_count > 0, "expected the generator's injected duplicates to be present in data/sample"

    def test_fallback_standardize_deduplicates_on_business_key(self, sample_pos_and_mapping):
        raw_pos, mapping = sample_pos_and_mapping
        standardized = _fallback_standardize("retail_pos_sales", raw_pos, mapping)

        key_cols = ["retailer_id", "store_id", "retailer_product_id", "transaction_date", "sales_channel"]
        assert standardized.duplicated(subset=key_cols).sum() == 0

    def test_fallback_standardize_drops_strictly_fewer_or_equal_rows_than_input(self, sample_pos_and_mapping):
        raw_pos, mapping = sample_pos_and_mapping
        standardized = _fallback_standardize("retail_pos_sales", raw_pos, mapping)
        assert len(standardized) <= len(raw_pos)
        assert len(standardized) > 0


class TestInvalidProductMappingHandling:
    def test_generator_actually_injected_invalid_retailer_product_ids(self, sample_pos_and_mapping):
        raw_pos, mapping = sample_pos_and_mapping
        valid_pairs = set(zip(mapping["retailer_id"], mapping["retailer_product_id"]))
        observed_pairs = set(zip(raw_pos["retailer_id"], raw_pos["retailer_product_id"]))
        unresolvable = observed_pairs - valid_pairs
        assert len(unresolvable) > 0, "expected the generator's injected invalid retailer_product_ids to be present"

    def test_fallback_standardize_drops_unresolvable_retailer_product_ids(self, sample_pos_and_mapping):
        raw_pos, mapping = sample_pos_and_mapping
        standardized = _fallback_standardize("retail_pos_sales", raw_pos, mapping)

        valid_pairs = set(zip(mapping["retailer_id"], mapping["retailer_product_id"]))
        observed_pairs = set(zip(standardized["retailer_id"], standardized["retailer_product_id"]))
        assert observed_pairs.issubset(valid_pairs)

    def test_fallback_standardize_resolves_product_id_for_every_remaining_row(self, sample_pos_and_mapping):
        raw_pos, mapping = sample_pos_and_mapping
        standardized = _fallback_standardize("retail_pos_sales", raw_pos, mapping)
        assert standardized["product_id"].notna().all()


class TestWarehouseIntegrity:
    """SQL-level confirmation that the same guarantees hold in the actual
    dbt-built warehouse (staging + marts), not just in the loader's Python
    logic. Skips cleanly if no warehouse database is reachable."""

    def test_fact_retail_sales_has_no_duplicate_business_keys(self, warehouse_engine):
        sql = """
            SELECT retailer_id, store_id, retailer_product_id, transaction_date, sales_channel, count(*) AS n
            FROM marts.fact_retail_sales
            GROUP BY 1, 2, 3, 4, 5
            HAVING count(*) > 1
        """
        with warehouse_engine.connect() as conn:
            dupes = conn.execute(text(sql)).fetchall()
        assert dupes == [], f"found {len(dupes)} duplicate business keys in fact_retail_sales"

    def test_fact_retail_sales_product_id_always_resolves_to_dim_product(self, warehouse_engine):
        sql = """
            SELECT count(*)
            FROM marts.fact_retail_sales fs
            LEFT JOIN marts.dim_product p ON fs.product_id = p.product_id
            WHERE p.product_id IS NULL
        """
        with warehouse_engine.connect() as conn:
            orphans = conn.execute(text(sql)).scalar()
        assert orphans == 0

    def test_fact_inventory_snapshot_has_no_duplicate_business_keys(self, warehouse_engine):
        sql = """
            SELECT retailer_id, store_id, retailer_product_id, snapshot_date, count(*) AS n
            FROM marts.fact_inventory_snapshot
            GROUP BY 1, 2, 3, 4
            HAVING count(*) > 1
        """
        with warehouse_engine.connect() as conn:
            dupes = conn.execute(text(sql)).fetchall()
        assert dupes == []
