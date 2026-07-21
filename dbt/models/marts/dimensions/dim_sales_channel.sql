{{ config(materialized='table') }}

-- Grain: one row per sales channel. Static reference data with no source
-- system of its own -- seeded directly (dbt/seeds/dim_sales_channel_seed.csv)
-- rather than staged from `landing`.
select
    {{ dbt_utils.generate_surrogate_key(['channel_code']) }} as channel_sk,
    channel_code,
    channel_name,
    channel_type
from {{ ref('dim_sales_channel_seed') }}
