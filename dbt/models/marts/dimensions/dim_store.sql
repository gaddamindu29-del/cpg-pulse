{{ config(materialized='table') }}

-- Grain: one row per store per historical version (SCD Type 2, built from
-- dbt/snapshots/dim_store_snapshot.sql).
select
    {{ dbt_utils.generate_surrogate_key(['store_id', 'dbt_valid_from']) }} as store_sk,
    store_id,
    retailer_id,
    store_name,
    city,
    state,
    region,
    store_format,
    latitude,
    longitude,
    opening_date,
    closing_date,
    (closing_date is not null) as is_closed,
    dbt_valid_from as effective_start_date,
    dbt_valid_to as effective_end_date,
    (dbt_valid_to is null) as is_current
from {{ ref('dim_store_snapshot') }}
