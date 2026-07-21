from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.common import Page, paginate
from ..models.products import ProductOut, ProductPerformanceOut
from ..services import products_service

router = APIRouter(tags=["products"])


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    category: str | None = Query(None, description="Filter by product category"),
    brand: str | None = Query(None, description="Filter by brand"),
    include_discontinued: bool = Query(False, description="Include discontinued products"),
) -> Page[ProductOut]:
    """List products from the current version of dim_product.

    Example: GET /products?category=Beverages&page=1&page_size=25
    """
    rows, total = products_service.list_products(page, page_size, category, brand, include_discontinued)
    return paginate([ProductOut(**r) for r in rows], page, page_size, total)


@router.get("/products/{product_id}/performance", response_model=ProductPerformanceOut)
def product_performance(product_id: str) -> ProductPerformanceOut:
    """Sales, inventory-risk, and promotion-activity rollup for one product.

    Example: GET /products/P00001/performance
    """
    row = products_service.get_product_performance(product_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return ProductPerformanceOut(**row)
