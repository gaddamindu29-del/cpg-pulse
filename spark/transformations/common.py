"""Shared PySpark transformation helpers used by every spark/jobs/standardize_*.py
script. Keeping these in one place is what lets each per-source job stay
short and focused on its own business logic (required columns, canonical-ID
resolution, validation rules) rather than re-implementing file reading,
lineage columns, deduplication, and quarantine writing six times.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F


def read_raw(spark: SparkSession, raw_path: str, fmt: str = "csv"):
    """Read every file for a source out of the raw layer, recursively (raw
    layer is partitioned `ingest_date=.../extract_date=...`). Returns an
    empty-but-schema-less DataFrame reader result if nothing has been landed
    yet -- callers should check `.rdd.isEmpty()` before proceeding, since Spark
    can't infer a schema from zero files.
    """
    reader = spark.read.option("recursiveFileLookup", "true")
    if fmt == "csv":
        return reader.option("header", "true").option("inferSchema", "true").csv(raw_path)
    if fmt == "json":
        return reader.json(raw_path)
    if fmt == "parquet":
        return reader.parquet(raw_path)
    raise ValueError(f"Unsupported format: {fmt}")


def add_lineage_columns(df: DataFrame, batch_id: str, source_file_col: str = "_source_file") -> DataFrame:
    """Attach standardization-time lineage. The raw layer intentionally does
    NOT carry these (it's a byte-exact copy of the source file) -- lineage is
    added here, where the row is first reshaped, per docs/architecture.md
    section 4.
    """
    df = df.withColumn("_standardized_at", F.current_timestamp())
    df = df.withColumn("_batch_id", F.lit(batch_id))
    if source_file_col not in df.columns:
        df = df.withColumn(source_file_col, F.input_file_name())
    return df


def rename_columns(df: DataFrame, alias_map: dict[str, str]) -> DataFrame:
    """Apply known column-name aliases (e.g. a retailer renaming a field in
    its feed mid-history: `reserved_qty` -> `reserved_units`). Only renames
    columns that are actually present, so this is safe to apply uniformly
    across both pre- and post-schema-change batches in the same job run.
    """
    for old_name, new_name in alias_map.items():
        if old_name in df.columns and new_name not in df.columns:
            df = df.withColumnRenamed(old_name, new_name)
        elif old_name in df.columns and new_name in df.columns:
            # both names present in this batch (e.g. a late pre-change file and
            # an on-time post-change file landed in the same extract_date) --
            # coalesce them into the canonical name rather than silently
            # dropping one.
            df = df.withColumn(new_name, F.coalesce(F.col(new_name), F.col(old_name))).drop(old_name)
    return df


def cast_columns(df: DataFrame, type_map: dict[str, str]) -> DataFrame:
    """Cast to an explicit target schema instead of trusting Spark/pandas type
    inference -- inferred dtypes can flip (e.g. int -> double) purely because
    a given batch happens to contain a null, which is not a real schema
    change. See docs/runbook.md "Known quirks" for the concrete case this
    guards against (observed during Phase 4 development on the inventory
    reserved_qty/reserved_units rename).
    """
    for col_name, dtype in type_map.items():
        if col_name in df.columns:
            df = df.withColumn(col_name, F.col(col_name).cast(dtype))
    return df


def deduplicate(df: DataFrame, key_cols: list[str], order_by_col: str = "_standardized_at") -> DataFrame:
    """Collapse exact business-key duplicates (e.g. the generator's injected
    `pos_duplicate_rate` resend simulation), keeping the most-recently-landed
    row per key. This is the standardized-layer dedup described in
    docs/architecture.md's layer-responsibilities table -- raw layer dedup is
    intentionally out of scope (raw = exact copy).
    """
    window = Window.partitionBy(*key_cols).orderBy(F.col(order_by_col).desc())
    return (
        df.withColumn("_dedup_rank", F.row_number().over(window))
        .filter(F.col("_dedup_rank") == 1)
        .drop("_dedup_rank")
    )


def split_valid_invalid(df: DataFrame, invalid_condition, reason_col_value: str) -> tuple[DataFrame, DataFrame]:
    """Partition a DataFrame into (valid, invalid) based on a boolean Column
    expression identifying invalid rows. Invalid rows get a `rejection_reason`
    column populated so they can be written straight to quarantine.
    """
    invalid = df.filter(invalid_condition).withColumn("rejection_reason", F.lit(reason_col_value))
    valid = df.filter(~invalid_condition)
    return valid, invalid


def write_standardized(df: DataFrame, output_path: str, partition_col: str) -> None:
    """Overwrite mode with dynamic partition overwrite: re-running
    standardization for the same business_date range replaces exactly those
    partitions rather than appending duplicate rows. This -- not a
    business-key merge -- is what makes standardization idempotent (see
    docs/architecture.md section 11): the caller controls idempotency by
    controlling which business_date partitions are in scope for a given run
    (see spark/jobs/standardize_pos_sales.py's --business-date-start/--end).
    """
    df.write.mode("overwrite").option("partitionOverwriteMode", "dynamic").partitionBy(partition_col).parquet(output_path)


def write_quarantine(df: DataFrame, output_path: str, partition_col: str) -> None:
    if df.rdd.isEmpty():
        return
    df.write.mode("overwrite").option("partitionOverwriteMode", "dynamic").partitionBy(partition_col).parquet(output_path)
