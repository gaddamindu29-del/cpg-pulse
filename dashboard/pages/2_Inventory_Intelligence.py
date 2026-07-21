"""Inventory Intelligence page: high-risk stockouts, excess inventory, days
of supply, and store/SKU filtering.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get_paginated_all

st.set_page_config(page_title="Inventory Intelligence -- CPG Pulse", page_icon="\U0001F4E6", layout="wide")
st.title("Inventory Intelligence")

with st.sidebar:
    st.header("Filters")
    retailer_id = st.text_input("Retailer ID (optional)", placeholder="e.g. RTL-WMT")
    store_id = st.text_input("Store ID (optional)", placeholder="e.g. S-WMT-0001")

try:
    stockout_rows = get_paginated_all("/inventory/stockout-risk", retailer_id=retailer_id or None, store_id=store_id or None)
    excess_rows = get_paginated_all("/inventory/excess-risk", retailer_id=retailer_id or None, store_id=store_id or None)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.stop()

if not stockout_rows and not excess_rows:
    st.warning("No inventory data for the selected filters. This reflects the latest available snapshot date.")
    st.stop()

df_stockout = pd.DataFrame(stockout_rows)
df_excess = pd.DataFrame(excess_rows)

snapshot_date = df_stockout["snapshot_date"].iloc[0] if not df_stockout.empty else (df_excess["snapshot_date"].iloc[0] if not df_excess.empty else None)
st.caption(f"Showing the latest available inventory snapshot: **{snapshot_date}**. Use the Sales Performance page for historical trends.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("HIGH Stockout Risk", int((df_stockout["stockout_risk_level"] == "HIGH").sum()) if not df_stockout.empty else 0)
col2.metric("MEDIUM Stockout Risk", int((df_stockout["stockout_risk_level"] == "MEDIUM").sum()) if not df_stockout.empty else 0)
col3.metric("CRITICAL Excess Inventory", int((df_excess["excess_inventory_risk_level"] == "CRITICAL").sum()) if not df_excess.empty else 0)
col4.metric("EXCESS Inventory", int((df_excess["excess_inventory_risk_level"] == "EXCESS").sum()) if not df_excess.empty else 0)

st.divider()
tab_stockout, tab_excess = st.tabs(["Stockout Risk", "Excess Inventory Risk"])

with tab_stockout:
    if df_stockout.empty:
        st.info("No stockout-risk data for the selected filters.")
    else:
        level_filter = st.multiselect("Risk level", options=["HIGH", "MEDIUM", "LOW", "NO_RECENT_DEMAND"], default=["HIGH", "MEDIUM"])
        filtered = df_stockout[df_stockout["stockout_risk_level"].isin(level_filter)] if level_filter else df_stockout
        fig = px.histogram(df_stockout, x="stockout_risk_level", category_orders={"stockout_risk_level": ["HIGH", "MEDIUM", "LOW", "NO_RECENT_DEMAND"]}, title="Stockout Risk Distribution")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            filtered.sort_values("days_of_supply", na_position="last")[
                ["retailer_id", "store_id", "product_id", "available_units", "avg_daily_units_sold", "days_of_supply", "velocity_trend", "stockout_risk_level"]
            ],
            use_container_width=True, hide_index=True,
        )

with tab_excess:
    if df_excess.empty:
        st.info("No excess-inventory data for the selected filters.")
    else:
        level_filter = st.multiselect("Risk level", options=["CRITICAL", "EXCESS", "NORMAL", "NO_RECENT_DEMAND"], default=["CRITICAL", "EXCESS"], key="excess_level_filter")
        filtered = df_excess[df_excess["excess_inventory_risk_level"].isin(level_filter)] if level_filter else df_excess
        fig = px.histogram(df_excess, x="excess_inventory_risk_level", category_orders={"excess_inventory_risk_level": ["CRITICAL", "EXCESS", "NORMAL", "NO_RECENT_DEMAND"]}, title="Excess Inventory Risk Distribution")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            filtered.sort_values("days_of_supply", ascending=False, na_position="last")[
                ["retailer_id", "store_id", "product_id", "available_units", "avg_daily_units_sold", "days_of_supply", "velocity_trend", "excess_inventory_risk_level"]
            ],
            use_container_width=True, hide_index=True,
        )
