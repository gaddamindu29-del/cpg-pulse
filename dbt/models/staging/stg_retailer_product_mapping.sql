select
    retailer_id,
    retailer_product_id,
    retailer_product_description,
    product_id,
    match_method,
    match_confidence::numeric(4, 3) as match_confidence,
    effective_start_date::date as effective_start_date,
    effective_end_date::date as effective_end_date,
    (effective_end_date is null) as is_current
from {{ source('landing', 'retailer_product_mapping') }}
