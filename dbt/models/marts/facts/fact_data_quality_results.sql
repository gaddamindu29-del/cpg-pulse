{{ config(materialized='table') }}

-- Grain: one row per data-quality check execution (run_id x table_name x
-- check_name x executed_at). Sourced from pipeline_meta.dq_results via the
-- landing.dq_results copy (docs/architecture.md section 4 -- the metadata
-- store is a separate physical database from the warehouse).

select
    dq_result_id,
    run_id,
    table_name,
    check_name,
    check_category,
    passed,
    records_checked,
    records_failed,
    case when records_checked > 0 then round(records_failed::numeric / records_checked, 4) else 0 end as failure_rate,
    failure_detail,
    executed_at,
    (to_char(executed_at::date, 'YYYYMMDD'))::int as date_sk
from {{ ref('stg_dq_results') }}
