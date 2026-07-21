"""Data Quality and Pipeline Operations page: latest pipeline runs, failed
checks, rejected records, freshness, and records processed by source.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiError, get, get_paginated_all

st.set_page_config(page_title="Data Quality & Pipeline Ops -- CPG Pulse", page_icon="\U0001F6E0", layout="wide")
st.title("Data Quality & Pipeline Operations")

try:
    dq_summary = get("/data-quality/latest")
    runs = get_paginated_all("/pipeline-runs", page_size=100, max_pages=5)
except ApiError as exc:
    st.error(f"Could not load data from the API ({exc.status_code}): {exc.detail}")
    st.stop()

df_dq = pd.DataFrame(dq_summary)
df_runs = pd.DataFrame(runs)

st.subheader("Data Quality Pass Rates")
if df_dq.empty:
    st.info(
        "No data-quality results yet. This table populates once "
        "spark/jobs/run_quality_checks.py has run at least once and its results "
        "have been synced into the warehouse (scripts/load_to_warehouse.py)."
    )
else:
    overall_pass_rate = (df_dq["checks_passed"].sum() / df_dq["total_checks_run"].sum()) if df_dq["total_checks_run"].sum() else None
    col1, col2, col3 = st.columns(3)
    col1.metric("Overall Pass Rate", f"{overall_pass_rate:.1%}" if overall_pass_rate is not None else "N/A")
    col2.metric("Tables Monitored", df_dq["table_name"].nunique())
    col3.metric("Total Records Failed", int(df_dq["total_records_failed"].sum()))

    fig = px.bar(df_dq.sort_values("pass_rate"), x="pass_rate", y="table_name", color="check_category", orientation="h", title="Pass Rate by Table and Check Category")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_dq, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Pipeline Run History")

if df_runs.empty:
    st.info("No pipeline runs recorded yet. Run `make seed` and an ingestion module (e.g. `python -m ingestion.retailer_sales.ingest`) to populate this.")
else:
    status_counts = df_runs["status"].value_counts()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Runs", len(df_runs))
    col2.metric("Succeeded", int(status_counts.get("SUCCEEDED", 0)))
    col3.metric("Failed", int(status_counts.get("FAILED", 0)))
    col4.metric("Records Rejected (sum)", int(df_runs["records_rejected"].sum()))

    by_source = df_runs.groupby("source_name", as_index=False).agg(
        runs=("run_id", "count"), records_read=("records_read", "sum"), records_rejected=("records_rejected", "sum"),
    )
    fig = px.bar(by_source.sort_values("records_read", ascending=True), x="records_read", y="source_name", orientation="h", title="Records Processed by Source")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Most recent runs**")
    st.dataframe(
        df_runs.sort_values("started_at", ascending=False)[
            ["started_at", "dag_id", "task_id", "source_name", "status", "records_read", "records_valid", "records_rejected", "duration_seconds"]
        ],
        use_container_width=True, hide_index=True,
    )

    failed = df_runs[df_runs["status"] == "FAILED"]
    if not failed.empty:
        st.markdown("**Failed runs**")
        st.dataframe(failed[["started_at", "dag_id", "task_id", "source_name", "error_message"]], use_container_width=True, hide_index=True)
