with source as (
    select * from {{ source('landing', 'ecommerce_orders') }}
),

deduped as (
    select
        *,
        row_number() over (partition by order_id, product_id order by order_date desc) as _rn
    from source
)

select
    order_id,
    order_date::date as order_date,
    customer_id,
    product_id,
    units_ordered::int as units_ordered,
    unit_price::numeric(10, 2) as unit_price,
    coalesce(discount_amount::numeric(12, 2), 0) as discount_amount,
    net_sales::numeric(12, 2) as net_sales,
    order_status,
    fulfillment_type,
    return_flag::boolean as return_flag
from deduped
where _rn = 1
