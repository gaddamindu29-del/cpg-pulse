from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.retailers import RetailerPerformanceOut
from ..services import retailers_service

router = APIRouter(tags=["retailers"])


@router.get("/retailers/{retailer_id}/performance", response_model=RetailerPerformanceOut)
def retailer_performance(retailer_id: str) -> RetailerPerformanceOut:
    """Sales, inventory-risk, and promotion-activity rollup for one retailer.

    Example: GET /retailers/RTL-WMT/performance
    """
    row = retailers_service.get_retailer_performance(retailer_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Retailer '{retailer_id}' not found")
    return RetailerPerformanceOut(**row)
