"""Tests for spark/quality/dq_engine.py, the config-driven data-quality
expectation engine (docs/architecture.md section 9).

Two tiers, deliberately separated:

1. Suite-loading and report-generation tests (`TestSuiteLoading`,
   `TestReportGeneration`) need no Spark runtime at all -- they run for real,
   always.
2. Check-execution tests (`TestCheckExecution`) need a working local
   SparkSession. This sandbox cannot run one: Spark 3.5.1's Python worker
   process crashes under Python 3.12 on Windows regardless of JDK version
   (verified again at the start of this Phase 8 session -- see
   docs/remaining_work.md section 5). The `spark_session` fixture below
   detects this at setup time and SKIPS (not fails, not fakes) those tests
   with a message pointing at the known cause, so this suite tells the truth
   about what was actually verified in whatever environment runs it -- on a
   working Docker/Linux Spark setup, the same tests will execute for real
   with no code changes.

Run: pytest tests/data_quality/test_dq_engine.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from spark.quality import dq_engine  # noqa: E402


class TestSuiteLoading:
    @pytest.mark.parametrize("suite_name,expected_table", [
        ("pos_sales_suite", "retail_pos_sales"),
        ("inventory_suite", "retail_inventory"),
        ("promotions_suite", "promotions"),
    ])
    def test_suite_loads_with_expected_table(self, suite_name, expected_table):
        suite = dq_engine.load_suite(suite_name)
        assert suite["table"] == expected_table
        assert isinstance(suite["checks"], list)
        assert len(suite["checks"]) > 0

    def test_all_suites_have_valid_check_structure(self):
        for suite_name in ("pos_sales_suite", "inventory_suite", "promotions_suite"):
            suite = dq_engine.load_suite(suite_name)
            for check in suite["checks"]:
                assert "name" in check
                assert "category" in check
                assert "type" in check
                assert check["type"] in (
                    "not_null", "min_value", "max_value", "accepted_values",
                    "unique_keys", "date_order", "freshness", "volume_check",
                    "referential_integrity",
                )

    def test_pos_sales_suite_covers_required_check_categories(self):
        """The original spec calls out specific DQ dimensions (PK uniqueness,
        required fields, positive values, accepted values, freshness, volume
        anomaly) -- confirm the flagship suite actually covers them, not just
        that the YAML parses."""
        suite = dq_engine.load_suite("pos_sales_suite")
        categories = {c["category"] for c in suite["checks"]}
        assert {"NULL_CHECK", "RANGE_CHECK", "UNIQUENESS", "ACCEPTED_VALUES", "FRESHNESS", "VOLUME_ANOMALY"}.issubset(categories)

    def test_promotions_suite_checks_start_before_end(self):
        """Original spec requirement: 'Promotion start date before end date'."""
        suite = dq_engine.load_suite("promotions_suite")
        date_order_checks = [c for c in suite["checks"] if c["type"] == "date_order"]
        assert len(date_order_checks) == 1
        assert date_order_checks[0]["start_column"] == "start_date"
        assert date_order_checks[0]["end_column"] == "end_date"

    def test_pos_sales_suite_checks_unreasonable_price_threshold(self):
        """Original spec requirement: 'Selling price not exceeding
        unreasonable thresholds'."""
        suite = dq_engine.load_suite("pos_sales_suite")
        price_checks = [c for c in suite["checks"] if c.get("column") == "selling_price"]
        assert len(price_checks) == 1
        assert price_checks[0]["type"] == "max_value"

    def test_missing_suite_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            dq_engine.load_suite("does_not_exist_suite")


class TestReportGeneration:
    def test_write_report_produces_valid_json_with_pass_rate(self, tmp_path):
        results = [
            dq_engine.CheckResult(name="check_a", category="NULL_CHECK", passed=True, records_checked=100, records_failed=0),
            dq_engine.CheckResult(name="check_b", category="RANGE_CHECK", passed=False, records_checked=100, records_failed=5, detail="5 rows out of range"),
        ]
        report_path = dq_engine.write_report("test_suite", results, output_dir=str(tmp_path))

        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["suite"] == "test_suite"
        assert report["pass_rate"] == 0.5
        assert len(report["checks"]) == 2
        assert report["checks"][1]["detail"] == "5 rows out of range"

    def test_write_report_handles_empty_results(self, tmp_path):
        report_path = dq_engine.write_report("empty_suite", [], output_dir=str(tmp_path))
        report = json.loads(report_path.read_text())
        assert report["pass_rate"] is None
        assert report["checks"] == []


@pytest.fixture(scope="module")
def spark_session():
    """Yields a real local SparkSession, or skips the test with a clear
    reason if one can't actually execute a job on this host -- see this
    file's module docstring."""
    try:
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder.appName("dq_engine_test")
            .master("local[1]")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        # Force real task execution (not just session creation) -- this is
        # exactly the step that crashes on this Windows/Python 3.12 host.
        spark.createDataFrame([(1,)], ["x"]).count()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"Local PySpark cannot execute a job in this environment ({type(exc).__name__}: "
            f"{str(exc)[:200]}). This is a known Windows + Python 3.12 + Spark 3.5.1 worker-process "
            "limitation (see docs/remaining_work.md section 5), not a dq_engine.py defect. "
            "Run this test suite inside the project's Docker Airflow container (Linux, Python 3.11) "
            "to actually execute it."
        )
    yield spark
    spark.stop()


class TestCheckExecution:
    """Needs a working local Spark job execution -- see the spark_session
    fixture above for why these are expected to SKIP on this host."""

    def test_not_null_check_passes_on_clean_data(self, spark_session):
        df = spark_session.createDataFrame([(1, "a"), (2, "b")], ["id", "val"])
        check = {"name": "id_not_null", "category": "NULL_CHECK", "type": "not_null", "column": "id"}
        result = dq_engine._run_check(df, check, reference_df=None, trailing_avg_count=None)
        assert result.passed
        assert result.records_failed == 0

    def test_not_null_check_fails_on_dirty_data(self, spark_session):
        df = spark_session.createDataFrame([(1, "a"), (None, "b")], ["id", "val"])
        check = {"name": "id_not_null", "category": "NULL_CHECK", "type": "not_null", "column": "id"}
        result = dq_engine._run_check(df, check, reference_df=None, trailing_avg_count=None)
        assert not result.passed
        assert result.records_failed == 1

    def test_unique_keys_check_detects_duplicates(self, spark_session):
        df = spark_session.createDataFrame([(1, "a"), (1, "a"), (2, "b")], ["id", "val"])
        check = {"name": "id_unique", "category": "UNIQUENESS", "type": "unique_keys", "columns": ["id", "val"]}
        result = dq_engine._run_check(df, check, reference_df=None, trailing_avg_count=None)
        assert not result.passed
        assert result.records_failed == 1  # one duplicate combination

    def test_referential_integrity_check_detects_orphans(self, spark_session):
        df = spark_session.createDataFrame([("P1",), ("P2",), ("P99",)], ["product_id"])
        ref = spark_session.createDataFrame([("P1",), ("P2",)], ["product_id"])
        check = {
            "name": "product_id_exists", "category": "REFERENTIAL_INTEGRITY", "type": "referential_integrity",
            "column": "product_id", "reference_column": "product_id",
        }
        result = dq_engine._run_check(df, check, reference_df=ref, trailing_avg_count=None)
        assert not result.passed
        assert result.records_failed == 1

    def test_run_suite_against_real_pos_sales_yaml(self, spark_session):
        df = spark_session.createDataFrame(
            [(1, "IN_STORE", 5.0), (2, "IN_STORE", 999.0)], ["retailer_id", "sales_channel", "selling_price"]
        )
        # Not every column the real suite references exists on this minimal
        # frame -- run_suite catches per-check exceptions and reports them as
        # failures rather than crashing the whole suite (dq_engine.py's
        # design), so this exercises that resilience path for real.
        results = dq_engine.run_suite(df, "pos_sales_suite")
        assert len(results) == len(dq_engine.load_suite("pos_sales_suite")["checks"])
