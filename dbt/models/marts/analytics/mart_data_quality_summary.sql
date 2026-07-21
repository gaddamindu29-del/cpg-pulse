{{ config(materialized='table') }}

-- Grain: table_name x check_category. Powers the /data-quality/latest API
-- endpoint and the dashboard's Data Quality & Pipeline Operations page
-- (docs/architecture.md section 9, "Generate a data-quality report for each
-- pipeline run" -- this is the aggregated, queryable counterpart to the
-- per-run JSON reports spark/quality/dq_engine.py writes to disk).

select
    table_name,
    check_category,
    count(*) as total_checks_run,
    count(*) filter (where passed) as checks_passed,
    round(count(*) filter (where passed)::numeric / nullif(count(*), 0), 4) as pass_rate,
    sum(records_checked) as total_records_checked,
    sum(records_failed) as total_records_failed,
    max(executed_at) as last_run_at
from {{ ref('fact_data_quality_results') }}
group by 1, 2
