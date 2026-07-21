from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from ..db import fetch_scalar, warehouse_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness + warehouse connectivity check. Returns 200 with
    warehouse_reachable=false rather than a 5xx if the DB is down --
    /health itself should stay up so orchestration/monitoring can
    distinguish "API process is dead" from "API is up but its DB isn't."
    """
    warehouse_reachable = True
    try:
        fetch_scalar(warehouse_engine(), "SELECT 1")
    except Exception:
        warehouse_reachable = False

    return {
        "status": "ok",
        "warehouse_reachable": warehouse_reachable,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
