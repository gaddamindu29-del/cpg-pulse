from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class DataQualitySummaryOut(BaseModel):
    table_name: str
    check_category: str
    total_checks_run: int
    checks_passed: int
    pass_rate: float | None = None
    total_records_checked: int
    total_records_failed: int
    last_run_at: dt.datetime | None = None


class PipelineRunOut(BaseModel):
    run_id: uuid.UUID
    dag_id: str
    task_id: str
    source_name: str | None = None
    run_type: str
    business_date: dt.date | None = None
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    duration_seconds: float | None = None
    status: str
    records_read: int
    records_valid: int
    records_rejected: int
    records_inserted: int
    records_updated: int
    retry_count: int
    source_file_count: int
    error_message: str | None = None
