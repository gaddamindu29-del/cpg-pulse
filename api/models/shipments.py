from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ShipmentReconciliationOut(BaseModel):
    """Backs GET /shipments/reconciliation. Not in the original 10-endpoint
    list (docs/architecture.md) -- added for the same reason as
    /sales/omnichannel: it's the only source for the Shipment Reconciliation
    dashboard page (shipment-vs-POS variance, reporting-delay/stockout-risk
    signals), which has no other endpoint to read from.
    """

    retailer_id: str
    product_id: str
    week_start: dt.date
    units_shipped: int
    units_sold: int
    variance_units: int
    variance_pct: float | None = None
    reconciliation_signal: str
