{{ config(materialized='table') }}

-- Grain: one row per promotion. SCD Type 1 -- a promotion's terms don't
-- change once a campaign is created in this dataset.
select
    {{ dbt_utils.generate_surrogate_key(['promotion_id']) }} as promotion_sk,
    promotion_id,
    retailer_id,
    product_id,
    promotion_type,
    start_date,
    end_date,
    (end_date - start_date + 1) as duration_days,
    regular_price,
    promotional_price,
    discount_percentage,
    display_type,
    marketing_spend
from {{ ref('stg_promotions') }}
