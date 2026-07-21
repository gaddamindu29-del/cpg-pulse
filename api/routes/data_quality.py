from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from ..models.common import Page, paginate
from ..models.data_quality import DataQualitySummaryOut, PipelineRunOut
from ..services import data_quality_service

router = APIRouter(tags=["data-quality"])


@router.get("/data-quality/latest", response_model=list[DataQualitySummaryOut])
def data_quality_latest(table_name: str | None = Query(None)) -> list[DataQualitySummaryOut]:
    """Aggregated data-quality pass rates by table and check category.

    Example: GET /data-quality/latest?table_name=retail_pos_sales
    """
    rows = data_quality_service.latest_data_quality(table_name)
    return [DataQualitySummaryOut(**r) for r in rows]


@router.get("/pipeline-runs", response_model=Page[PipelineRunOut])
def pipeline_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    source_name: str | None = Query(None),
    status: str | None = Query(None, pattern="^(RUNNING|SUCCEEDED|FAILED|SKIPPED)$"),
    dag_id: str | None = Query(None),
    since: dt.datetime | None = Query(None, description="Only runs started at or after this timestamp"),
) -> Page[PipelineRunOut]:
    """Pipeline run history from pipeline_meta.pipeline_runs, most recent first.

    Example: GET /pipeline-runs?status=FAILED&page=1&page_size=25
    """
    rows, total = data_quality_service.list_pipeline_runs(page, page_size, source_name, status, dag_id, since)
    return paginate([PipelineRunOut(**r) for r in rows], page, page_size, total)
