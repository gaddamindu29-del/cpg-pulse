{{ config(materialized='view') }}

-- Grain: product_id x sale_date x channel_type. Unifies retail POS sales
-- (in-store + retailer-operated online/marketplace channels) with CPG
-- Pulse's own direct-to-consumer e-commerce orders into one comparable
-- "channel_type" axis -- the basis for mart_omnichannel_performance.sql and
-- for the dashboard's "physical vs. e-commerce" comparison. Returns are
-- excluded from the DTC side (return_flag = false) so this reflects
-- recognized sales, not gross order volume.
--
-- channel_type is coalesced to 'UNKNOWN' defensively: a row with a null or
-- unrecognized sales_channel should have been quarantined by standardization
-- (spark/jobs/standardize_pos_sales.py rejects it), but the local-dev
-- fallback loader (scripts/load_to_warehouse.py, used when Spark hasn't
-- actually run) is deliberately simpler and doesn't apply that rule -- so a
-- handful of such rows can reach this model in local dev. Coalescing keeps
-- them as an explicit, visible bucket instead of a silent blank-string group
-- in the aggregated marts.

with retail as (
    select
        fs.retailer_id,
        fs.product_id,
        fs.transaction_date as sale_date,
        coalesce(ch.channel_type, 'UNKNOWN') as channel_type,
        fs.units_sold,
        fs.net_sales
    from {{ ref('fact_retail_sales') }} fs
    left join {{ ref('dim_sales_channel') }} ch on fs.channel_sk = ch.channel_sk
),

ecommerce as (
    select
        cast(null as text) as retailer_id,
        fe.product_id,
        fe.order_date as sale_date,
        'E-commerce' as channel_type,
        fe.units_ordered as units_sold,
        fe.net_sales
    from {{ ref('fact_ecommerce_orders') }} fe
    where not fe.return_flag
)

select * from retail
union all
select * from ecommerce
