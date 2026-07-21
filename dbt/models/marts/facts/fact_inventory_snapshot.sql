{{
    config(
        materialized='incremental',
        unique_key='inventory_sk',
        incremental_strategy='delete+insert',
    )
}}

-- Grain: one row per retailer x store x retailer_product x snapshot_date.

with inventory as (
    select * from {{ ref('stg_retail_inventory') }}
    {% if is_incremental() %}
    where snapshot_date > (select coalesce(max(snapshot_date), '1900-01-01') from {{ this }})
    {% endif %}
),

current_product as (
    select * from {{ ref('dim_product') }} where is_current
),

current_store as (
    select * from {{ ref('dim_store') }} where is_current
)

select
    {{ dbt_utils.generate_surrogate_key(['i.retailer_id', 'i.store_id', 'i.retailer_product_id', 'i.snapshot_date']) }} as inventory_sk,
    p.product_sk,
    st.store_sk,
    r.retailer_sk,
    (to_char(i.snapshot_date, 'YYYYMMDD'))::int as date_sk,
    i.retailer_id,
    i.store_id,
    i.retailer_product_id,
    i.product_id,
    i.snapshot_date,
    i.on_hand_units,
    i.on_order_units,
    i.reserved_units,
    i.available_units
from inventory i
left join current_product p on i.product_id = p.product_id
left join current_store st on i.store_id = st.store_id
left join {{ ref('dim_retailer') }} r on i.retailer_id = r.retailer_id
