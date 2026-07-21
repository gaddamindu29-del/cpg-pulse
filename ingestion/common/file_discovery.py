"""Source file discovery.

Transactional sources (POS sales, inventory, shipments, e-commerce orders) are
written by the generator into `extract_date=YYYY-MM-DD/` partitions -- these
stand in for "the date the retailer's file landed," which is exactly what a
real SFTP/EDI drop or API pull looks like. Discovery walks those partitions
and returns only the ones newer than the watermark (or within an explicit
backfill range), which is what makes ingestion incremental rather than a full
reload every run (docs/architecture.md section 10).

Reference sources (product master, store master, ...) are full-snapshot
files with no date partitioning -- discovery just returns the one current
snapshot file per format.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiscoveredBatch:
    extract_date: dt.date | None  # None for reference/snapshot sources
    files: list[Path]


def discover_partitioned_files(
    generated_dir: str,
    fmt: str,
    since: dt.date | None,
    backfill_range: tuple[dt.date, dt.date] | None = None,
) -> list[DiscoveredBatch]:
    root = Path(generated_dir) / fmt
    if not root.exists():
        return []

    batches: list[DiscoveredBatch] = []
    for partition_dir in sorted(root.glob("extract_date=*")):
        date_str = partition_dir.name.split("=", 1)[1]
        extract_date = dt.date.fromisoformat(date_str)

        if backfill_range is not None:
            start, end = backfill_range
            if not (start <= extract_date <= end):
                continue
        elif since is not None and extract_date <= since:
            continue

        files = sorted(partition_dir.glob(f"*.{fmt}"))
        if files:
            batches.append(DiscoveredBatch(extract_date=extract_date, files=files))

    return batches


def discover_reference_file(generated_dir: str, fmt: str) -> DiscoveredBatch | None:
    root = Path(generated_dir) / fmt
    if not root.exists():
        return None
    files = sorted(root.glob(f"*.{fmt}"))
    if not files:
        return None
    return DiscoveredBatch(extract_date=None, files=files)
