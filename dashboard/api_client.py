"""Thin HTTP client the dashboard uses to talk to the FastAPI service.

The dashboard never queries the warehouse directly (docs/architecture.md
section 5) -- every page goes through this client, which wraps `requests`
with a shared base URL, error handling, and Streamlit response caching so
switching filters doesn't re-hit the API for identical requests.
"""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.environ.get("DASHBOARD_API_BASE_URL", "http://localhost:8000")


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


@st.cache_data(ttl=60, show_spinner=False)
def _get(path: str, params: tuple) -> Any:
    """`params` is a tuple of (key, value) pairs -- st.cache_data requires
    hashable arguments, and dicts aren't hashable, so callers pass a tuple
    and this function converts it back.
    """
    param_dict = {k: v for k, v in params if v is not None}
    try:
        resp = requests.get(f"{API_BASE_URL}{path}", params=param_dict, timeout=10)
    except requests.exceptions.RequestException as exc:
        raise ApiError(503, f"Could not reach the API at {API_BASE_URL}: {exc}") from exc

    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise ApiError(resp.status_code, detail)
    return resp.json()


def get(path: str, **params: Any) -> Any:
    return _get(path, tuple(sorted(params.items())))


def get_paginated_all(path: str, page_size: int = 200, max_pages: int = 25, **params: Any) -> list[dict]:
    """Pull every page from a paginated endpoint, up to `max_pages` (a safety
    cap -- the dashboard summarizes/charts data, it doesn't need unbounded
    results). Returns the concatenated `items` lists.
    """
    all_items: list[dict] = []
    page = 1
    while page <= max_pages:
        result = get(path, page=page, page_size=page_size, **params)
        all_items.extend(result["items"])
        if page >= result["total_pages"]:
            break
        page += 1
    return all_items
