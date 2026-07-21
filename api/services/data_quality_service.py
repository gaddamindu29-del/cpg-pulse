"""Query layer for /data-quality/latest and /pipeline-runs."""

from __future__ import annotations

import datetime as dt

from ..db import fetch_all, fetch_scalar, metadata_engine, warehouse_engine


def latest_data_quality(table_name: str | None) -> list[dict]:
    where = "WHERE table_name = :table_name" if table_name else ""
    params = {"table_name": table_name} if table_name else {}
    return fetch_all(
        warehouse_engine(),
        f"""
        SELECT table_name, check_category, total_checks_run, checks_passed, pass_rate,
               total_records_checked, total_records_failed, last_run_at
        FROM marts.mart_data_quality_summary
        {where}
        ORDER BY table_name, check_category
        """,
        params,
    )


def list_pipeline_runs(
    page: int, page_size: int, source_name: str | None, status: str | None,
    dag_id: str | None, since: dt.datetime | None,
) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if source_name:
        where.append("source_name = :source_name")
        params["source_name"] = source_name
    if status:
        where.append("status = :status")
        params["status"] = status
    if dag_id:
        where.append("dag_id = :dag_id")
        params["dag_id"] = dag_id
    if since:
        where.append("started_at >= :since")
        params["since"] = since
    where_clause = " AND ".join(where)

    total = fetch_scalar(metadata_engine(), f"SELECT count(*) FROM pipeline_meta.pipeline_runs WHERE {where_clause}", params)
    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        metadata_engine(),
        f"""
        SELECT run_id, dag_id, task_id, source_name, run_type, business_date, started_at,
               ended_at, duration_seconds, status, records_read, records_valid,
               records_rejected, records_inserted, records_updated, retry_count,
               source_file_count, error_message
        FROM pipeline_meta.pipeline_runs
        WHERE {where_clause}
        ORDER BY started_at DESC
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total
