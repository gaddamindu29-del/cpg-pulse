from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from ..models.common import Page, paginate
from ..models.shipments import ShipmentReconciliationOut
from ..services import shipments_service

router = APIRouter(tags=["shipments"])

_VALID_SIGNALS = (
    "MISSING_SHIPMENT_DATA_OR_REPORTING_DELAY",
    "MISSING_POS_DATA_OR_REPORTING_DELAY",
    "SHIPMENTS_OUTPACING_SALES_INVENTORY_BUILDUP",
    "SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT",
    "ALIGNED",
)


@router.get("/shipments/reconciliation", response_model=Page[ShipmentReconciliationOut])
def shipment_reconciliation(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    retailer_id: str | None = Query(None),
    signal: str | None = Query(None, description=f"One of: {', '.join(_VALID_SIGNALS)}"),
    since: dt.date | None = Query(None, description="Only weeks starting on or after this date"),
) -> Page[ShipmentReconciliationOut]:
    """Weekly manufacturer-shipment-vs-consumer-POS variance by retailer x product.

    Example: GET /shipments/reconciliation?signal=SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT
    """
    rows, total = shipments_service.list_reconciliation(page, page_size, retailer_id, signal, since)
    return paginate([ShipmentReconciliationOut(**r) for r in rows], page, page_size, total)
