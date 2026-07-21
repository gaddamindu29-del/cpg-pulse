{{ config(materialized='table') }}

-- Grain: one row per retailer. SCD Type 1 (overwrite) -- retailer banners are
-- effectively static reference data; a dbt snapshot would be overkill here.
select
    {{ dbt_utils.generate_surrogate_key(['retailer_id']) }} as retailer_sk,
    retailer_id,
    retailer_name,
    retailer_type
from {{ ref('stg_retailers') }}
