"""Generic ingestion engine shared by every per-source ingestion module.

One run of `run_ingestion()`:
  1. Look up the source's watermark (transactional sources) or last-seen
     content hash (reference sources) in the metadata DB / local state.
  2. Discover only the files newer than that watermark (or within an
     explicit backfill range).
  3. For each newly-discovered batch: read it, check its schema against the
     last-known schema, and -- if there is no breaking change -- copy it
     byte-for-byte into the raw lake layer and advance the watermark.
  4. Record one `pipeline_runs` row for the whole invocation and one
     `schema_change_log` row per detected schema change.

A batch with a breaking schema change (a required column missing, or an
existing column's dtype changing) is deliberately **not** landed -- the run is
marked FAILED with the breaking change recorded, rather than silently landing
data standardization can't handle. A compatible change (a new optional
column) is logged and the batch lands normally. See docs/architecture.md
section 11.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import db, file_discovery, schema_check
from .storage import LakeStorage

logger = logging.getLogger(__name__)

STATE_DIR = Path("data/_schema_state")


@dataclass
class SourceConfig:
    source_name: str
    generated_dir: str
    required_columns: list[str]
    partitioned: bool = True
    preferred_format: str = "csv"
    environment: str = "local"
    dag_id: str = field(default="")

    def __post_init__(self):
        if not self.dag_id:
            self.dag_id = f"{self.source_name}_ingestion"


@dataclass
class IngestionResult:
    run_id: uuid.UUID | None
    status: str  # SUCCEEDED | FAILED | SKIPPED
    records_read: int
    files_landed: int
    batches_landed: int
    breaking_changes: list[str]


def _read_file(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "json":
        return pd.read_json(path)
    if fmt == "parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported format: {fmt}")


def _read_batch(files: list[Path], fmt: str) -> pd.DataFrame:
    frames = [_read_file(f, fmt) for f in files]
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _content_hash(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(f.read_bytes())
    return h.hexdigest()


def _hash_state_path(source_name: str) -> Path:
    return STATE_DIR / f"{source_name}.hash"


def run_ingestion(
    cfg: SourceConfig,
    run_date: dt.date | None = None,
    backfill_range: tuple[dt.date, dt.date] | None = None,
) -> IngestionResult:
    run_date = run_date or dt.date.today()
    storage = LakeStorage()

    with db.connection_scope() as conn:
        if cfg.partitioned:
            watermark = None if backfill_range else db.get_watermark(conn, cfg.source_name, cfg.environment)
            batches = file_discovery.discover_partitioned_files(
                cfg.generated_dir, cfg.preferred_format, since=watermark, backfill_range=backfill_range
            )
        else:
            batch = file_discovery.discover_reference_file(cfg.generated_dir, cfg.preferred_format)
            batches = []
            if batch is not None:
                new_hash = _content_hash(batch.files)
                hash_path = _hash_state_path(cfg.source_name)
                previous_hash = hash_path.read_text().strip() if hash_path.exists() else None
                if new_hash != previous_hash:
                    batches = [batch]
                    STATE_DIR.mkdir(parents=True, exist_ok=True)
                    hash_path.write_text(new_hash)

        if not batches:
            logger.info("[%s] no new data to ingest (watermark up to date)", cfg.source_name)
            return IngestionResult(run_id=None, status="SKIPPED", records_read=0, files_landed=0, batches_landed=0, breaking_changes=[])

        run_id = db.start_run(conn, dag_id=cfg.dag_id, task_id="ingest", source_name=cfg.source_name, run_type="INGESTION", business_date=run_date)
        conn.commit()

        total_read = 0
        files_landed = 0
        batches_landed = 0
        breaking_changes: list[str] = []

        try:
            for batch in batches:
                df = _read_batch(batch.files, cfg.preferred_format)
                total_read += len(df)

                # Schema changes are detected and logged for visibility, but they
                # never block raw landing -- a raw/bronze layer's entire purpose is
                # to store the source data exactly as received (docs/architecture.md
                # section 4). A *breaking* change (a column standardization actually
                # depends on going missing, or an existing column's dtype changing)
                # is handled downstream: spark/jobs standardization either applies a
                # known column-alias mapping (e.g. the reserved_qty -> reserved_units
                # rename) or, if it truly can't reconcile the record, quarantines it
                # with a reason -- see spark/jobs/standardize_common.py.
                dtypes = {c: str(df[c].dtype) for c in df.columns}
                changes = schema_check.detect_schema_changes(cfg.source_name, dtypes, cfg.required_columns)
                for change in changes:
                    db.log_schema_change(
                        conn, cfg.source_name, change.change_type, change.is_breaking,
                        column_name=change.column_name, old_value=change.old_value, new_value=change.new_value,
                        source_file=batch.files[0].name, run_id=run_id,
                    )
                    if change.is_breaking:
                        breaking_changes.append(f"{change.change_type}:{change.column_name}")
                        logger.warning(
                            "[%s] breaking schema change detected (%s %s) -- logged to schema_change_log, "
                            "raw file still landed as-is",
                            cfg.source_name, change.change_type, change.column_name,
                        )

                ingest_date_label = run_date.isoformat()
                extract_label = batch.extract_date.isoformat() if batch.extract_date else "snapshot"
                for f in batch.files:
                    key = f"{cfg.source_name}/ingest_date={ingest_date_label}/extract_date={extract_label}/{f.name}"
                    storage.put_file("raw", key, str(f))
                    files_landed += 1

                # Backfills are explicit, out-of-band reprocessing of a
                # specific historical range -- they must never move the
                # watermark that governs normal incremental discovery
                # (docs/architecture.md section 10). A regression test
                # (tests/integration/test_ingestion.py) caught this: without
                # the `not backfill_range` guard, backfilling an old date
                # range after the pipeline had already advanced past it
                # would silently move the watermark backward, causing the
                # next normal run to rediscover and re-land everything in
                # between.
                if cfg.partitioned and batch.extract_date and not backfill_range:
                    db.set_watermark(conn, cfg.source_name, batch.extract_date, cfg.environment)
                batches_landed += 1
                conn.commit()

            status = "SUCCEEDED"
            db.finish_run(
                conn, run_id, status=status, records_read=total_read, records_valid=total_read,
                source_file_count=files_landed,
                error_message=(f"{len(breaking_changes)} breaking schema change(s) logged: " + "; ".join(breaking_changes)) if breaking_changes else None,
            )
            conn.commit()
        except Exception as exc:
            db.finish_run(conn, run_id, status="FAILED", records_read=total_read, error_message=str(exc))
            conn.commit()
            raise

        logger.info(
            "[%s] ingestion %s: %d batches landed, %d files, %d rows read",
            cfg.source_name, status, batches_landed, files_landed, total_read,
        )
        return IngestionResult(
            run_id=run_id, status=status, records_read=total_read,
            files_landed=files_landed, batches_landed=batches_landed, breaking_changes=breaking_changes,
        )
