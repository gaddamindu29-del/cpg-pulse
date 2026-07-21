"""Database access layer. Two engines: `warehouse_engine` (marts/analytics --
what almost every endpoint reads) and `metadata_engine` (pipeline_meta.* --
only /pipeline-runs and, as a fallback, /data-quality/latest use this
directly).

All queries go through `fetch_all`/`fetch_one`, which always use bound
parameters (never string-formatted SQL) -- see docs/architecture.md section
13 ("SQL is always parameterized... in the API's service layer").
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import settings

_warehouse_engine: Engine | None = None
_metadata_engine: Engine | None = None


def warehouse_engine() -> Engine:
    global _warehouse_engine
    if _warehouse_engine is None:
        _warehouse_engine = create_engine(settings.warehouse_url, pool_pre_ping=True)
    return _warehouse_engine


def metadata_engine() -> Engine:
    global _metadata_engine
    if _metadata_engine is None:
        _metadata_engine = create_engine(settings.metadata_url, pool_pre_ping=True)
    return _metadata_engine


def fetch_all(engine: Engine, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings()]


def fetch_one(engine: Engine, sql: str, params: Mapping[str, Any] | None = None) -> dict | None:
    rows = fetch_all(engine, sql, params)
    return rows[0] if rows else None


def fetch_scalar(engine: Engine, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()
