{{ config(materialized='table') }}

-- Grain: one row per product per historical version (SCD Type 2, built from
-- the dbt snapshot in dbt/snapshots/dim_product_snapshot.sql -- see that
-- file's docstring for which attributes are tracked and why).
select
    {{ dbt_utils.generate_surrogate_key(['product_id', 'dbt_valid_from']) }} as product_sk,
    product_id,
    upc,
    brand,
    category,
    subcategory,
    product_name,
    flavor,
    package_size,
    case_quantity,
    unit_cost,
    launch_date,
    discontinued_date,
    (discontinued_date is not null) as is_discontinued,
    dbt_valid_from as effective_start_date,
    dbt_valid_to as effective_end_date,
    (dbt_valid_to is null) as is_current
from {{ ref('dim_product_snapshot') }}
