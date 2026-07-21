"""Promotion Analytics page: lift, incremental units, ROI, best/worst promotions.

Estimated lift/ROI figures are an analytical estimate (baseline-vs-actual
comparison over comparable non-promotional days), not a causal-inference
result -- see docs/metrics.md for the full methodology and its limitations.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get_paginated_all

st.set_page_config(page_title="Promotion Analytics -- CPG Pulse", page_icon="\U0001F3F7", layout="wide")
st.title("Promotion Analytics")
st.info(
    "Lift and ROI below are **analytical estimates** (actual promo-period sales vs. an "
    "estimated baseline from comparable non-promotional days) -- not a causal-inference result. "
    "See docs/metrics.md for the full methodology and known limitations."
)

with st.sidebar:
    st.header("Filters")
    retailer_id = st.text_input("Retailer ID (optional)", placeholder="e.g. RTL-WMT")
    promotion_type = st.text_input("Promotion type (optional)", placeholder="e.g. Digital Coupon")

try:
    promos = get_paginated_all("/promotions/performance", retailer_id=retailer_id or None, promotion_type=promotion_type or None)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.stop()

if not promos:
    st.warning("No promotions match the selected filters.")
    st.stop()

df = pd.DataFrame(promos)
df_with_lift = df[df["lift_percentage"].notna()]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Promotions", len(df))
col2.metric("Median Lift", f"{df_with_lift['lift_percentage'].median():,.0f}%" if not df_with_lift.empty else "N/A")
col3.metric("Total Incremental Revenue", f"${df['incremental_revenue'].sum():,.0f}")
col4.metric("Total Marketing Spend", f"${df['marketing_spend'].sum():,.0f}")

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Best-Performing Promotions (by lift %)")
    st.dataframe(
        df_with_lift.sort_values("lift_percentage", ascending=False).head(10)[
            ["promotion_id", "retailer_id", "product_id", "promotion_type", "lift_percentage", "promotion_roi", "incremental_units"]
        ],
        use_container_width=True, hide_index=True,
    )
with col_b:
    st.subheader("Worst-Performing Promotions (by lift %)")
    st.dataframe(
        df_with_lift.sort_values("lift_percentage", ascending=True).head(10)[
            ["promotion_id", "retailer_id", "product_id", "promotion_type", "lift_percentage", "promotion_roi", "incremental_units"]
        ],
        use_container_width=True, hide_index=True,
    )

st.subheader("ROI by Promotion Type")
by_type = df.groupby("promotion_type", as_index=False).agg(avg_roi=("promotion_roi", "mean"), avg_lift=("lift_percentage", "mean"), promotion_count=("promotion_id", "count"))
fig = px.bar(by_type.sort_values("avg_roi", ascending=True), x="avg_roi", y="promotion_type", orientation="h", labels={"avg_roi": "Average ROI", "promotion_type": "Promotion Type"})
st.plotly_chart(fig, use_container_width=True)

with st.expander("All promotions"):
    st.dataframe(df, use_container_width=True, hide_index=True)
