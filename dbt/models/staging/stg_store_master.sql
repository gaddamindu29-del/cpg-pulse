select
    store_id,
    retailer_id,
    store_name,
    city,
    state,
    region,
    store_format,
    latitude::numeric(9, 5) as latitude,
    longitude::numeric(9, 5) as longitude,
    opening_date::date as opening_date,
    closing_date::date as closing_date,
    (closing_date is not null) as is_closed
from {{ source('landing', 'store_master') }}
