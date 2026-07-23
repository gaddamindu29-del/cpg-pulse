"""Multi-format output writers.

Two writing patterns are used, matching how the two kinds of source data
actually arrive in a real CPG integration:

- **Reference/master data** (`write_reference_dataset`): one full snapshot file
  per format, e.g. a nightly full-file product master extract.
- **Transactional data** (`write_partitioned_dataset`): one file per format per
  `_extract_date` -- the date the source system's file actually landed -- which
  is what makes the raw lake layer's `ingest_date` partitioning
  (docs/architecture.md Raw Layer) and late-arriving-data handling meaningful.
  The `_extract_date` column itself is dropped from the written row content
  (a real retailer file wouldn't include "the date I sent this file" as a
  column; that's metadata carried by the file's name/location).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_FORMATS = ("csv", "json", "parquet")


def _json_default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")


def _write_one_file(df: pd.DataFrame, path_no_ext: Path, fmt: str) -> Path:
    path_no_ext.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        out = path_no_ext.with_suffix(".csv")
        df.to_csv(out, index=False)
    elif fmt == "json":
        out = path_no_ext.with_suffix(".json")
        records = df.to_dict(orient="records")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(records, fh, default=_json_default, indent=None)
    elif fmt == "parquet":
        out = path_no_ext.with_suffix(".parquet")
        parquet_df = df.copy()
        for col in parquet_df.columns:
            if parquet_df[col].dtype == object:
                sample = parquet_df[col].dropna()
                if not sample.empty and hasattr(sample.iloc[0], "isoformat"):
                    parquet_df[col] = pd.to_datetime(parquet_df[col])
        parquet_df.to_parquet(out, index=False)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    return out


def write_reference_dataset(df: pd.DataFrame, source_name: str, output_dir: str, formats=DEFAULT_FORMATS) -> list[Path]:
    written = []
    for fmt in formats:
        path_no_ext = Path(output_dir) / source_name / fmt / source_name
        written.append(_write_one_file(df, path_no_ext, fmt))
    logger.info("wrote reference dataset '%s': %d rows, formats=%s", source_name, len(df), formats)
    return written


def write_partitioned_dataset(
    df: pd.DataFrame,
    source_name: str,
    output_dir: str,
    formats=DEFAULT_FORMATS,
    extract_date_col: str = "_extract_date",
    file_suffix: str = "",
) -> list[Path]:
    """`file_suffix` disambiguates filenames when the same source is written in
    multiple passes that can land in the same extract_date partition (e.g. a
    pre-schema-change generation and a post-schema-change generation) -- without
    it, the second write would silently overwrite the first for any date where
    both passes happen to produce a file.
    """
    if extract_date_col not in df.columns:
        raise ValueError(f"{source_name}: expected '{extract_date_col}' column for partitioned write")

    written = []
    n_files = 0
    for extract_date, group in df.groupby(extract_date_col):
        payload = group.drop(columns=[extract_date_col])
        date_str = pd.Timestamp(extract_date).strftime("%Y-%m-%d")
        for fmt in formats:
            path_no_ext = (
                Path(output_dir) / source_name / fmt / f"extract_date={date_str}" / f"{source_name}_{date_str}{file_suffix}"
            )
            written.append(_write_one_file(payload, path_no_ext, fmt))
        n_files += 1
    logger.info(
        "wrote partitioned dataset '%s': %d rows across %d extract dates, formats=%s",
        source_name, len(df), n_files, formats,
    )
    return written
