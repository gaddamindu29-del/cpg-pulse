"""Lightweight, config-driven data-quality expectation engine.

docs/architecture.md documents that Great Expectations itself was evaluated
and not used (dependency weight vs. this project's Airflow image constraints)
in favor of an in-house engine that follows the same *pattern* GE is known
for: checks are declarative (YAML, not code), each check produces a
pass/fail result with counts, and every run produces both a database record
(`pipeline_meta.dq_results`) and a human-readable report file. This module is
that engine.

A suite file (spark/quality/expectations/*.yml) is a list of checks against
one table:

    table: retail_pos_sales
    checks:
      - name: units_sold_positive
        category: RANGE_CHECK
        type: min_value
        column: units_sold
        min: 1

Supported check `type`s: not_null, min_value, max_value, accepted_values,
unique_keys, date_order, freshness, volume_check, referential_integrity.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

logger = logging.getLogger(__name__)

SUITE_DIR = Path(__file__).parent / "expectations"


@dataclass
class CheckResult:
    name: str
    category: str
    passed: bool
    records_checked: int
    records_failed: int
    detail: str | None = None


def load_suite(suite_name: str) -> dict:
    path = SUITE_DIR / f"{suite_name}.yml"
    with open(path) as fh:
        return yaml.safe_load(fh)


def _run_check(df: DataFrame, check: dict, reference_df: DataFrame | None, trailing_avg_count: int | None) -> CheckResult:
    check_type = check["type"]
    name, category = check["name"], check["category"]
    total = df.count()

    if check_type == "not_null":
        col = check["column"]
        failed = df.filter(F.col(col).isNull()).count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} nulls in {col}")

    if check_type == "min_value":
        col, min_val = check["column"], check["min"]
        failed = df.filter((F.col(col).isNull()) | (F.col(col) < min_val)).count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} rows with {col} < {min_val}")

    if check_type == "max_value":
        col, max_val = check["column"], check["max"]
        failed = df.filter(F.col(col) > max_val).count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} rows with {col} > {max_val}")

    if check_type == "accepted_values":
        col, values = check["column"], check["values"]
        failed = df.filter(~F.col(col).isin(values) | F.col(col).isNull()).count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} rows with {col} outside {values}")

    if check_type == "unique_keys":
        cols = check["columns"]
        dup_count = total - df.select(*cols).dropDuplicates().count()
        return CheckResult(name, category, dup_count == 0, total, dup_count, f"{dup_count} duplicate key combinations on {cols}")

    if check_type == "date_order":
        start_col, end_col = check["start_column"], check["end_column"]
        failed = df.filter(F.col(start_col) > F.col(end_col)).count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} rows with {start_col} after {end_col}")

    if check_type == "freshness":
        date_col, max_lag_days = check["date_column"], check["max_lag_days"]
        max_date_row = df.agg(F.max(date_col).alias("max_date")).collect()[0]
        max_date = max_date_row["max_date"]
        if max_date is None:
            return CheckResult(name, category, False, total, total, "no rows to evaluate freshness on")
        lag_days = (dt.date.today() - max_date).days if isinstance(max_date, dt.date) else None
        passed = lag_days is not None and lag_days <= max_lag_days
        return CheckResult(name, category, passed, total, 0 if passed else total, f"latest {date_col}={max_date}, lag={lag_days}d, threshold={max_lag_days}d")

    if check_type == "volume_check":
        tolerance_pct = check["tolerance_pct"]
        if trailing_avg_count is None or trailing_avg_count == 0:
            return CheckResult(name, category, True, total, 0, "no trailing baseline yet -- skipped")
        pct_change = abs(total - trailing_avg_count) / trailing_avg_count * 100
        passed = pct_change <= tolerance_pct
        return CheckResult(name, category, passed, total, 0 if passed else total, f"row count {total} vs trailing avg {trailing_avg_count} ({pct_change:.1f}% change, threshold {tolerance_pct}%)")

    if check_type == "referential_integrity":
        col, ref_col = check["column"], check["reference_column"]
        if reference_df is None:
            raise ValueError(f"check '{name}' requires a reference_df but none was provided")
        valid_values = reference_df.select(F.col(ref_col).alias("_ref")).distinct()
        failed = df.join(valid_values, df[col] == valid_values["_ref"], how="left_anti").count()
        return CheckResult(name, category, failed == 0, total, failed, f"{failed} rows with {col} not found in reference.{ref_col}")

    raise ValueError(f"Unknown check type: {check_type}")


def run_suite(
    df: DataFrame,
    suite_name: str,
    reference_df: DataFrame | None = None,
    trailing_avg_count: int | None = None,
) -> list[CheckResult]:
    suite = load_suite(suite_name)
    results = []
    for check in suite["checks"]:
        try:
            result = _run_check(df, check, reference_df, trailing_avg_count)
        except Exception as exc:  # noqa: BLE001 -- a broken check must not crash the whole run
            logger.exception("check %s raised an exception", check["name"])
            result = CheckResult(check["name"], check["category"], False, 0, 0, f"check raised exception: {exc}")
        results.append(result)
        level = logging.INFO if result.passed else logging.WARNING
        logger.log(level, "[%s] %s: %s (checked=%d failed=%d)", suite["table"], result.name, "PASS" if result.passed else "FAIL", result.records_checked, result.records_failed)
    return results


def write_report(suite_name: str, results: list[CheckResult], output_dir: str = "data/dq_reports") -> Path:
    """Human-readable per-run report artifact (docs/architecture.md section 9,
    "Generate a data-quality report for each pipeline run")."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    report = {
        "suite": suite_name,
        "generated_at": dt.datetime.utcnow().isoformat(),
        "pass_rate": round(sum(r.passed for r in results) / len(results), 4) if results else None,
        "checks": [r.__dict__ for r in results],
    }
    path = Path(output_dir) / f"{suite_name}_{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    return path
