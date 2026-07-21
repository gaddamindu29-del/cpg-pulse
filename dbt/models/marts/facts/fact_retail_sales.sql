{{
    config(
        materialized='incremental',
        unique_key='sales_sk',
        incremental_strategy='delete+insert',
    )
}}

-- Grain: one row per retailer x store x retailer_product x transaction_date x
-- sales_channel (docs/architecture.md section 8). Surrogate keys join out to
-- dim_product/dim_store as of the *current* SCD2 version at query time --
-- point-in-time-correct SCD2 joins (as-of transaction_date) are deliberately
-- left to the query/BI layer rather than baked into the fact, since "which
-- product attributes were true when this sale happened" vs. "how do I see
-- this sale under today's product hierarchy" are both legitimate, different
-- analytical questions.

with sales as (
    select * from {{ ref('stg_retail_pos_sales') }}
    {% if is_incremental() %}
    where transaction_date > (select coalesce(max(transaction_date), '1900-01-01') from {{ this }})
    {% endif %}
),

current_product as (
    select * from {{ ref('dim_product') }} where is_current
),

current_store as (
    select * from {{ ref('dim_store') }} where is_current
)

select
    {{ dbt_utils.generate_surrogate_key(['s.retailer_id', 's.store_id', 's.retailer_product_id', 's.transaction_date', 's.sales_channel']) }} as sales_sk,
    p.product_sk,
    st.store_sk,
    r.retailer_sk,
    (to_char(s.transaction_date, 'YYYYMMDD'))::int as date_sk,
    ch.channel_sk,
    s.retailer_id,
    s.store_id,
    s.retailer_product_id,
    s.product_id,
    s.transaction_date,
    s.sales_channel,
    s.units_sold,
    s.gross_sales,
    s.discount_amount,
    s.net_sales,
    s.regular_price,
    s.selling_price
from sales s
left join current_product p on s.product_id = p.product_id
left join current_store st on s.store_id = st.store_id
left join {{ ref('dim_retailer') }} r on s.retailer_id = r.retailer_id
left join {{ ref('dim_sales_channel') }} ch on s.sales_channel = ch.channel_code
