"""Unit tests for ingestion/common/{schema_check,file_discovery,storage}.py --
pure logic, no database, no generated data, no Spark required. Everything
here runs in isolated tmp_path directories so it never touches the real
data/_schema_state or data/lake used by the integration tests / real runs.

Run: pytest tests/unit/test_ingestion_common.py -v
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ingestion.common import file_discovery, schema_check  # noqa: E402
from ingestion.common.storage import LakeStorage  # noqa: E402


# ---------------------------------------------------------------------------
# schema_check.py
# ---------------------------------------------------------------------------

class TestSchemaCheck:
    @pytest.fixture(autouse=True)
    def isolated_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(schema_check, "STATE_DIR", tmp_path / "_schema_state")

    def test_first_run_has_no_changes_and_caches_schema(self):
        changes = schema_check.detect_schema_changes("src_a", {"a": "int64", "b": "object"}, required_columns=["a", "b"])
        assert changes == []
        assert schema_check.load_last_known_schema("src_a") == {"a": "int64", "b": "object"}

    def test_new_optional_column_is_compatible(self):
        schema_check.detect_schema_changes("src_b", {"a": "int64"}, required_columns=["a"])
        changes = schema_check.detect_schema_changes("src_b", {"a": "int64", "new_col": "object"}, required_columns=["a"])

        assert len(changes) == 1
        assert changes[0].change_type == "COLUMN_ADDED"
        assert changes[0].column_name == "new_col"
        assert changes[0].is_breaking is False

    def test_removed_required_column_is_breaking(self):
        schema_check.detect_schema_changes("src_c", {"a": "int64", "b": "object"}, required_columns=["a", "b"])
        changes = schema_check.detect_schema_changes("src_c", {"a": "int64"}, required_columns=["a", "b"])

        assert len(changes) == 1
        assert changes[0].change_type == "COLUMN_REMOVED"
        assert changes[0].column_name == "b"
        assert changes[0].is_breaking is True

    def test_removed_optional_column_is_compatible(self):
        schema_check.detect_schema_changes("src_d", {"a": "int64", "optional": "object"}, required_columns=["a"])
        changes = schema_check.detect_schema_changes("src_d", {"a": "int64"}, required_columns=["a"])

        assert len(changes) == 1
        assert changes[0].change_type == "COLUMN_REMOVED"
        assert changes[0].is_breaking is False

    def test_dtype_change_on_existing_column_is_always_breaking(self):
        schema_check.detect_schema_changes("src_e", {"a": "int64"}, required_columns=[])
        changes = schema_check.detect_schema_changes("src_e", {"a": "float64"}, required_columns=[])

        assert len(changes) == 1
        assert changes[0].change_type == "TYPE_CHANGED"
        assert changes[0].is_breaking is True
        assert changes[0].old_value == "int64"
        assert changes[0].new_value == "float64"

    def test_reserved_qty_to_reserved_units_rename_looks_like_remove_plus_add(self):
        """Regression test mirroring the real scenario this schema-check
        logic exists to catch (scripts/data_gen/quality_issues.py): a
        retailer renames a column. From a pure column-set diff, a rename is
        indistinguishable from "remove old + add new" -- confirm that's
        exactly what gets reported (one breaking COLUMN_REMOVED for the
        required old name, one compatible COLUMN_ADDED for the new one)."""
        schema_check.detect_schema_changes("retail_inventory", {"reserved_qty": "int64"}, required_columns=["reserved_qty"])
        changes = schema_check.detect_schema_changes("retail_inventory", {"reserved_units": "int64"}, required_columns=["reserved_qty"])

        by_type = {c.change_type: c for c in changes}
        assert by_type["COLUMN_REMOVED"].column_name == "reserved_qty"
        assert by_type["COLUMN_REMOVED"].is_breaking is True
        assert by_type["COLUMN_ADDED"].column_name == "reserved_units"
        assert by_type["COLUMN_ADDED"].is_breaking is False

    def test_no_changes_when_schema_is_identical(self):
        schema_check.detect_schema_changes("src_f", {"a": "int64", "b": "object"}, required_columns=["a"])
        changes = schema_check.detect_schema_changes("src_f", {"a": "int64", "b": "object"}, required_columns=["a"])
        assert changes == []


# ---------------------------------------------------------------------------
# file_discovery.py
# ---------------------------------------------------------------------------

class TestFileDiscovery:
    def _make_partitioned_source(self, tmp_path, dates: list[str], fmt="csv"):
        root = tmp_path / "source" / fmt
        for date_str in dates:
            partition = root / f"extract_date={date_str}"
            partition.mkdir(parents=True)
            (partition / f"file_{date_str}.{fmt}").write_text("a,b\n1,2\n")
        return tmp_path / "source"

    def test_discovers_all_partitions_when_no_watermark(self, tmp_path):
        source_dir = self._make_partitioned_source(tmp_path, ["2025-01-01", "2025-01-02", "2025-01-03"])
        batches = file_discovery.discover_partitioned_files(str(source_dir), "csv", since=None)
        assert len(batches) == 3
        assert [b.extract_date for b in batches] == [dt.date(2025, 1, 1), dt.date(2025, 1, 2), dt.date(2025, 1, 3)]

    def test_watermark_excludes_partitions_at_or_before_it(self, tmp_path):
        source_dir = self._make_partitioned_source(tmp_path, ["2025-01-01", "2025-01-02", "2025-01-03"])
        batches = file_discovery.discover_partitioned_files(str(source_dir), "csv", since=dt.date(2025, 1, 2))
        assert [b.extract_date for b in batches] == [dt.date(2025, 1, 3)]

    def test_backfill_range_overrides_watermark(self, tmp_path):
        source_dir = self._make_partitioned_source(tmp_path, ["2025-01-01", "2025-01-02", "2025-01-03"])
        batches = file_discovery.discover_partitioned_files(
            str(source_dir), "csv", since=dt.date(2025, 1, 3), backfill_range=(dt.date(2025, 1, 1), dt.date(2025, 1, 1)),
        )
        assert [b.extract_date for b in batches] == [dt.date(2025, 1, 1)]

    def test_missing_source_directory_returns_empty_list(self, tmp_path):
        batches = file_discovery.discover_partitioned_files(str(tmp_path / "does_not_exist"), "csv", since=None)
        assert batches == []

    def test_empty_partition_directory_is_skipped(self, tmp_path):
        source_dir = self._make_partitioned_source(tmp_path, ["2025-01-01"])
        (source_dir / "csv" / "extract_date=2025-01-02").mkdir()  # no files inside
        batches = file_discovery.discover_partitioned_files(str(source_dir), "csv", since=None)
        assert len(batches) == 1
        assert batches[0].extract_date == dt.date(2025, 1, 1)

    def test_discover_reference_file_returns_none_when_missing(self, tmp_path):
        result = file_discovery.discover_reference_file(str(tmp_path / "nope"), "csv")
        assert result is None

    def test_discover_reference_file_finds_snapshot(self, tmp_path):
        root = tmp_path / "product_master" / "csv"
        root.mkdir(parents=True)
        (root / "product_master.csv").write_text("product_id\nP1\n")
        result = file_discovery.discover_reference_file(str(tmp_path / "product_master"), "csv")
        assert result is not None
        assert result.extract_date is None
        assert len(result.files) == 1


# ---------------------------------------------------------------------------
# storage.py
# ---------------------------------------------------------------------------

class TestLakeStorage:
    def test_defaults_to_local_backend(self, monkeypatch):
        monkeypatch.delenv("CPG_PULSE_STORAGE_BACKEND", raising=False)
        storage = LakeStorage(local_root="unused")
        assert storage.backend == "local"

    def test_put_file_copies_bytes_exactly(self, tmp_path):
        source_file = tmp_path / "source.csv"
        source_file.write_bytes(b"retailer_id,units\nRTL-WMT,5\n")

        storage = LakeStorage(backend="local", local_root=str(tmp_path / "lake"))
        dest = storage.put_file("raw", "retail_pos_sales/extract_date=2025-01-01/source.csv", str(source_file))

        assert Path(dest).read_bytes() == source_file.read_bytes()

    def test_exists_reflects_actual_file_presence(self, tmp_path):
        storage = LakeStorage(backend="local", local_root=str(tmp_path / "lake"))
        assert storage.exists("raw", "some/key.csv") is False

        storage.put_bytes("raw", "some/key.csv", b"data")
        assert storage.exists("raw", "some/key.csv") is True

    def test_layer_root_returns_local_path_for_local_backend(self, tmp_path):
        storage = LakeStorage(backend="local", local_root=str(tmp_path / "lake"))
        assert storage.layer_root("standardized") == str(tmp_path / "lake" / "standardized")
