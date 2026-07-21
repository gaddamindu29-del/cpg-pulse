with source as (
    select * from {{ source('landing', 'retail_inventory') }}
),

deduped as (
    select
        *,
        row_number() over (
            partition by retailer_id, store_id, retailer_product_id, snapshot_date
            order by snapshot_date desc
        ) as _rn
    from source
)

select
    retailer_id,
    store_id,
    retailer_product_id,
    product_id,
    snapshot_date::date as snapshot_date,
    on_hand_units::int as on_hand_units,
    coalesce(on_order_units::int, 0) as on_order_units,
    coalesce(reserved_units::int, 0) as reserved_units,
    available_units::int as available_units
from deduped
where _rn = 1
