"""Shipment Reconciliation page: manufacturer shipments vs. consumer POS
sales, inventory buildup, and potential supply gaps.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get_paginated_all

st.set_page_config(page_title="Shipment Reconciliation -- CPG Pulse", page_icon="\U0001F69A", layout="wide")
st.title("Shipment Reconciliation")
st.caption("Weekly manufacturer shipments into retailer DCs vs. consumer POS sales, by retailer x product.")

with st.sidebar:
    st.header("Filters")
    retailer_id = st.text_input("Retailer ID (optional)", placeholder="e.g. RTL-WMT")
    signal = st.selectbox(
        "Signal",
        options=[
            None, "ALIGNED", "SHIPMENTS_OUTPACING_SALES_INVENTORY_BUILDUP",
            "SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT",
            "MISSING_SHIPMENT_DATA_OR_REPORTING_DELAY", "MISSING_POS_DATA_OR_REPORTING_DELAY",
        ],
        format_func=lambda v: "All" if v is None else v,
    )

try:
    rows = get_paginated_all("/shipments/reconciliation", retailer_id=retailer_id or None, signal=signal)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.stop()

if not rows:
    st.warning("No reconciliation data for the selected filters.")
    st.stop()

df = pd.DataFrame(rows)

signal_counts = df["reconciliation_signal"].value_counts()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Aligned Weeks", int(signal_counts.get("ALIGNED", 0)))
col2.metric("Inventory Buildup Signals", int(signal_counts.get("SHIPMENTS_OUTPACING_SALES_INVENTORY_BUILDUP", 0)))
col3.metric("Potential Stockout Signals", int(signal_counts.get("SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT", 0)))
col4.metric(
    "Missing Data Signals",
    int(signal_counts.get("MISSING_SHIPMENT_DATA_OR_REPORTING_DELAY", 0) + signal_counts.get("MISSING_POS_DATA_OR_REPORTING_DELAY", 0)),
)

st.divider()

col_a, col_b = st.columns([1, 2])
with col_a:
    fig = px.pie(names=signal_counts.index, values=signal_counts.values, title="Reconciliation Signal Mix")
    st.plotly_chart(fig, use_container_width=True)

with col_b:
    weekly = df.groupby("week_start", as_index=False).agg(units_shipped=("units_shipped", "sum"), units_sold=("units_sold", "sum"))
    weekly_long = weekly.melt(id_vars="week_start", value_vars=["units_shipped", "units_sold"], var_name="metric", value_name="units")
    fig = px.line(weekly_long, x="week_start", y="units", color="metric", title="Shipments vs. POS Sales Over Time")
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Weeks with a supply-gap or buildup signal")
flagged = df[df["reconciliation_signal"] != "ALIGNED"].sort_values("week_start", ascending=False)
st.dataframe(flagged, use_container_width=True, hide_index=True)
