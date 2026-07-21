with source as (
    select * from {{ source('landing', 'retail_pos_sales') }}
),

deduped as (
    -- Defense in depth: standardization (spark/jobs/standardize_pos_sales.py)
    -- already dedupes on this business key, but staging re-asserts it so a
    -- dbt run is never silently wrong if the landing load ever bypasses Spark
    -- (e.g. the local-dev fallback path in scripts/load_to_warehouse.py).
    select
        *,
        row_number() over (
            partition by retailer_id, store_id, retailer_product_id, transaction_date, sales_channel
            order by transaction_date desc
        ) as _rn
    from source
)

select
    retailer_id,
    store_id,
    retailer_product_id,
    product_id,
    transaction_date::date as transaction_date,
    units_sold::int as units_sold,
    gross_sales::numeric(12, 2) as gross_sales,
    coalesce(discount_amount::numeric(12, 2), 0) as discount_amount,
    net_sales::numeric(12, 2) as net_sales,
    regular_price::numeric(10, 2) as regular_price,
    selling_price::numeric(10, 2) as selling_price,
    sales_channel
from deduped
where _rn = 1
