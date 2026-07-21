select
    dq_result_id,
    run_id,
    table_name,
    check_name,
    check_category,
    passed::boolean as passed,
    records_checked::bigint as records_checked,
    records_failed::bigint as records_failed,
    failure_detail,
    executed_at::timestamp as executed_at
from {{ source('landing', 'dq_results') }}
