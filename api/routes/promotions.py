from __future__ import annotations

from fastapi import APIRouter, Query

from ..models.common import Page, paginate
from ..models.promotions import PromotionPerformanceOut
from ..services import promotions_service

router = APIRouter(tags=["promotions"])


@router.get("/promotions/performance", response_model=Page[PromotionPerformanceOut])
def promotion_performance(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    retailer_id: str | None = Query(None),
    promotion_type: str | None = Query(None),
    min_lift_percentage: float | None = Query(None, description="Only promotions with at least this estimated lift %"),
) -> Page[PromotionPerformanceOut]:
    """Estimated promotion lift/ROI, ranked highest lift first.

    This is an analytical estimate (baseline vs. actual comparison), not a
    causal-inference result -- see docs/metrics.md.

    Example: GET /promotions/performance?retailer_id=RTL-WMT&min_lift_percentage=50
    """
    rows, total = promotions_service.list_promotion_performance(page, page_size, retailer_id, promotion_type, min_lift_percentage)
    return paginate([PromotionPerformanceOut(**r) for r in rows], page, page_size, total)
