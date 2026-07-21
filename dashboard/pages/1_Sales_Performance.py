"""Sales Performance page: by retailer, product, brand, category, and
physical vs. e-commerce channel comparison.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="Sales Performance -- CPG Pulse", page_icon="\U0001F4C8", layout="wide")
st.title("Sales Performance")

with st.sidebar:
    st.header("Filters")
    date_range = st.date_input("Date range", value=(dt.date(2025, 1, 1), dt.date(2025, 12, 31)))
    start_date, end_date = (date_range if len(date_range) == 2 else (date_range[0], date_range[0]))
    retailer_id = st.text_input("Retailer ID (optional)", placeholder="e.g. RTL-WMT")

try:
    by_retailer = get("/sales/summary", group_by="retailer", start_date=start_date, end_date=end_date, retailer_id=retailer_id or None)
    by_product = get("/sales/summary", group_by="product", start_date=start_date, end_date=end_date, retailer_id=retailer_id or None)
    by_brand = get("/sales/summary", group_by="brand", start_date=start_date, end_date=end_date, retailer_id=retailer_id or None)
    by_category = get("/sales/summary", group_by="category", start_date=start_date, end_date=end_date, retailer_id=retailer_id or None)
    omnichannel = get("/sales/omnichannel", start_date=start_date, end_date=end_date)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.stop()

if not by_retailer:
    st.warning("No sales data for the selected filters.")
    st.stop()

tab_retailer, tab_product, tab_category, tab_channel = st.tabs(["By Retailer", "By Product / Brand", "By Category", "Physical vs. E-commerce"])

with tab_retailer:
    df = pd.DataFrame(by_retailer).sort_values("net_sales", ascending=True)
    fig = px.bar(df, x="net_sales", y="group_label", orientation="h", labels={"net_sales": "Net Sales ($)", "group_label": "Retailer"}, title="Net Sales by Retailer")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df[["group_label", "units_sold", "gross_sales", "net_sales", "avg_selling_price", "discount_rate"]], use_container_width=True, hide_index=True)

with tab_product:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Top 15 products by net sales**")
        df_p = pd.DataFrame(by_product).sort_values("net_sales", ascending=False).head(15)
        st.dataframe(df_p[["group_key", "group_label", "units_sold", "net_sales"]], use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**Net sales by brand**")
        df_b = pd.DataFrame(by_brand).sort_values("net_sales", ascending=True)
        fig = px.bar(df_b, x="net_sales", y="group_label", orientation="h", labels={"net_sales": "Net Sales ($)", "group_label": "Brand"})
        st.plotly_chart(fig, use_container_width=True)

with tab_category:
    df_c = pd.DataFrame(by_category)
    fig = px.pie(df_c, names="group_label", values="net_sales", title="Net Sales Share by Category")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_c[["group_label", "units_sold", "net_sales", "discount_rate"]], use_container_width=True, hide_index=True)

with tab_channel:
    df_ch = pd.DataFrame(omnichannel)
    if df_ch.empty:
        st.info("No channel data for this date range.")
    else:
        summary = df_ch.groupby("channel_type", as_index=False).agg(units_sold=("units_sold", "sum"), net_sales=("net_sales", "sum"))
        col_a, col_b = st.columns(2)
        with col_a:
            fig = px.pie(summary, names="channel_type", values="net_sales", title="Net Sales Share by Channel")
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            daily = df_ch.groupby(["sale_date", "channel_type"], as_index=False)["net_sales"].sum()
            fig = px.line(daily, x="sale_date", y="net_sales", color="channel_type", title="Channel Trend Over Time")
            st.plotly_chart(fig, use_container_width=True)
