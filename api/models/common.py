"""Shared response envelope types."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total_items: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)


def paginate(items: list[T], page: int, page_size: int, total_items: int) -> Page[T]:
    total_pages = (total_items + page_size - 1) // page_size if page_size else 0
    return Page[T](items=items, page=page, page_size=page_size, total_items=total_items, total_pages=total_pages)


class ErrorResponse(BaseModel):
    detail: str
