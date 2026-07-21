"""Thin data-access layer over the pipeline_meta.* tables
(warehouse/postgres/metadata_schema.sql). Used by ingestion, Spark
standardization, and the DQ validators to record watermarks, run history,
schema-change events, and quarantine entries.

Every function takes an open psycopg2 connection rather than owning
connection lifecycle -- callers (CLI entrypoints, Airflow tasks) control
when the connection opens/closes/commits, which matters for making a whole
ingestion run atomic (see `base_ingest.run_ingestion`, which commits the
watermark advance and the run's SUCCEEDED status together).
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional


def get_connection():
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get("METADATA_DB_HOST", "localhost"),
        port=int(os.environ.get("METADATA_DB_PORT", "5432")),
        dbname=os.environ.get("METADATA_DB_NAME", "cpg_pulse_metadata"),
        user=os.environ.get("METADATA_DB_USER", "cpgpulse"),
        password=os.environ.get("METADATA_DB_PASSWORD", "cpgpulse_dev_password"),
    )


@contextmanager
def connection_scope() -> Iterator["psycopg2.extensions.connection"]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_watermark(conn, source_name: str, environment: str = "local") -> Optional[dt.date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_business_date FROM pipeline_meta.watermarks WHERE source_name = %s AND environment = %s",
            (source_name, environment),
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_watermark(conn, source_name: str, business_date: dt.date, environment: str = "local") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_meta.watermarks (source_name, environment, last_business_date, last_ingested_at, updated_at)
            VALUES (%s, %s, %s, now(), now())
            ON CONFLICT (source_name, environment)
            DO UPDATE SET last_business_date = EXCLUDED.last_business_date,
                          last_ingested_at = EXCLUDED.last_ingested_at,
                          updated_at = now()
            """,
            (source_name, environment, business_date),
        )


def start_run(conn, dag_id: str, task_id: str, source_name: str, run_type: str, business_date: Optional[dt.date] = None) -> uuid.UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_meta.pipeline_runs
                (run_id, dag_id, task_id, source_name, run_type, business_date, started_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, now(), 'RUNNING')
            """,
            (str(run_id), dag_id, task_id, source_name, run_type, business_date),
        )
    return run_id


def finish_run(
    conn,
    run_id: uuid.UUID,
    status: str,
    records_read: int = 0,
    records_valid: int = 0,
    records_rejected: int = 0,
    records_inserted: int = 0,
    records_updated: int = 0,
    retry_count: int = 0,
    source_file_count: int = 0,
    error_message: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_meta.pipeline_runs
            SET ended_at = now(), status = %s, records_read = %s, records_valid = %s,
                records_rejected = %s, records_inserted = %s, records_updated = %s,
                retry_count = %s, source_file_count = %s, error_message = %s
            WHERE run_id = %s
            """,
            (status, records_read, records_valid, records_rejected, records_inserted,
             records_updated, retry_count, source_file_count, error_message, str(run_id)),
        )


def log_schema_change(
    conn,
    source_name: str,
    change_type: str,
    is_breaking: bool,
    column_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    source_file: Optional[str] = None,
    run_id: Optional[uuid.UUID] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_meta.schema_change_log
                (schema_change_id, source_name, change_type, is_breaking, column_name, old_value, new_value, source_file, run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), source_name, change_type, is_breaking, column_name, old_value, new_value, source_file, str(run_id) if run_id else None),
        )


def log_quarantine(
    conn,
    run_id: uuid.UUID,
    source_name: str,
    business_date: Optional[dt.date],
    rejection_reason: str,
    record_count: int,
    quarantine_file_path: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_meta.quarantine_log
                (quarantine_id, run_id, source_name, business_date, rejection_reason, record_count, quarantine_file_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), str(run_id), source_name, business_date, rejection_reason, record_count, quarantine_file_path),
        )


def log_dq_result(
    conn,
    run_id: uuid.UUID,
    table_name: str,
    check_name: str,
    check_category: str,
    passed: bool,
    records_checked: int = 0,
    records_failed: int = 0,
    failure_detail: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_meta.dq_results
                (dq_result_id, run_id, table_name, check_name, check_category, passed, records_checked, records_failed, failure_detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), str(run_id), table_name, check_name, check_category, passed, records_checked, records_failed, failure_detail),
        )
