"""CPG Pulse dashboard -- Executive Overview (the entry page; Streamlit
auto-discovers the other five pages under dashboard/pages/).

Run locally: `make dashboard` (streamlit run dashboard/app.py)
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get, get_paginated_all

st.set_page_config(page_title="CPG Pulse -- Executive Overview", page_icon="\U0001F4CA", layout="wide")

ECOMMERCE_CHANNEL_TYPES = {"E-commerce", "Marketplace", "Omnichannel"}

st.title("CPG Pulse -- Executive Overview")
st.caption("Omnichannel sales, inventory, and promotion intelligence")

with st.sidebar:
    st.header("Filters")
    date_range = st.date_input(
        "Date range",
        value=(dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
        help="Applies to sales, e-commerce share, and promotion metrics on this page.",
    )
    start_date, end_date = (date_range if len(date_range) == 2 else (date_range[0], date_range[0]))

try:
    sales_by_retailer = get("/sales/summary", group_by="retailer", start_date=start_date, end_date=end_date)
    omnichannel = get("/sales/omnichannel", start_date=start_date, end_date=end_date)
    stockout_page = get("/inventory/stockout-risk", risk_level="HIGH", page=1, page_size=1)
    promotions = get_paginated_all("/promotions/performance", page_size=200)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.info("Is the API running? Expected at the URL configured via DASHBOARD_API_BASE_URL.")
    st.stop()

if not sales_by_retailer:
    st.warning("No sales data found for the selected date range. Try widening the date filter.")
    st.stop()

total_net_sales = sum(r["net_sales"] for r in sales_by_retailer)
total_units_sold = sum(r["units_sold"] for r in sales_by_retailer)

ecommerce_net_sales = sum(r["net_sales"] for r in omnichannel if r["channel_type"] in ECOMMERCE_CHANNEL_TYPES)
total_omnichannel_net_sales = sum(r["net_sales"] for r in omnichannel)
ecommerce_share = (ecommerce_net_sales / total_omnichannel_net_sales) if total_omnichannel_net_sales else None

high_stockout_risk_count = stockout_page["total_items"]

lift_values = [p["lift_percentage"] for p in promotions if p["lift_percentage"] is not None]
avg_lift = sum(lift_values) / len(lift_values) if lift_values else None

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Net Sales", f"${total_net_sales:,.0f}")
col2.metric("Units Sold", f"{total_units_sold:,}")
col3.metric("E-commerce Sales Share", f"{ecommerce_share:.1%}" if ecommerce_share is not None else "N/A")
col4.metric("High Stockout-Risk Snapshots", f"{high_stockout_risk_count:,}")
col5.metric("Avg. Estimated Promotion Lift", f"{avg_lift:,.0f}%" if avg_lift is not None else "N/A")

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Sales by Retailer")
    df_retailer = pd.DataFrame(sales_by_retailer)
    if not df_retailer.empty:
        fig = px.bar(df_retailer.sort_values("net_sales", ascending=True), x="net_sales", y="group_label", orientation="h", labels={"net_sales": "Net Sales ($)", "group_label": "Retailer"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No retailer sales data for this date range.")

with right:
    st.subheader("Sales Trend by Channel Type")
    df_channel = pd.DataFrame(omnichannel)
    if not df_channel.empty:
        daily = df_channel.groupby(["sale_date", "channel_type"], as_index=False)["net_sales"].sum()
        fig = px.line(daily, x="sale_date", y="net_sales", color="channel_type", labels={"sale_date": "Date", "net_sales": "Net Sales ($)", "channel_type": "Channel"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No channel data for this date range.")

st.caption(
    "Promotion lift is an analytical estimate (baseline-vs-actual comparison), not a causal-inference result. "
    "See the Promotion Analytics page and docs/metrics.md for the full methodology and caveats."
)
