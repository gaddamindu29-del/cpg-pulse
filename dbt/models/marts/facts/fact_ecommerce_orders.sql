{{
    config(
        materialized='incremental',
        unique_key='ecommerce_order_sk',
        incremental_strategy='delete+insert',
    )
}}

-- Grain: one row per order_id x product_id (an order can contain more than
-- one line, though this dataset generates one product per order for
-- simplicity -- see scripts/data_gen/ecommerce.py).

with orders as (
    select * from {{ ref('stg_ecommerce_orders') }}
    {% if is_incremental() %}
    where order_date > (select coalesce(max(order_date), '1900-01-01') from {{ this }})
    {% endif %}
),

current_product as (
    select * from {{ ref('dim_product') }} where is_current
)

select
    {{ dbt_utils.generate_surrogate_key(['o.order_id', 'o.product_id']) }} as ecommerce_order_sk,
    p.product_sk,
    ch.channel_sk,
    (to_char(o.order_date, 'YYYYMMDD'))::int as date_sk,
    o.order_id,
    o.order_date,
    o.customer_id,
    o.product_id,
    o.units_ordered,
    o.unit_price,
    o.discount_amount,
    o.net_sales,
    o.order_status,
    o.fulfillment_type,
    o.return_flag
from orders o
left join current_product p on o.product_id = p.product_id
left join {{ ref('dim_sales_channel') }} ch on ch.channel_code = 'DTC_ECOMMERCE'
