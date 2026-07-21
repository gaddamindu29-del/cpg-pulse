{{ config(materialized='table') }}

-- Grain: retailer_id x product_id x week_start. Compares manufacturer
-- shipments into a retailer's DC against consumer POS sales out of that
-- retailer's stores for the same product/week (docs/architecture.md
-- "Shipment-to-POS Reconciliation"). A FULL OUTER JOIN is used deliberately:
-- a week with shipments but no matching POS rows (or vice versa) is itself a
-- signal (missing data / reporting delay), not something to silently drop
-- via an inner join.

with weekly_shipments as (
    select
        retailer_id,
        product_id,
        date_trunc('week', shipment_date)::date as week_start,
        sum(units_shipped) as units_shipped
    from {{ ref('fact_shipments') }}
    group by 1, 2, 3
),

weekly_sales as (
    select
        retailer_id,
        product_id,
        date_trunc('week', transaction_date)::date as week_start,
        sum(units_sold) as units_sold
    from {{ ref('fact_retail_sales') }}
    group by 1, 2, 3
),

combined as (
    select
        coalesce(sh.retailer_id, sa.retailer_id) as retailer_id,
        coalesce(sh.product_id, sa.product_id) as product_id,
        coalesce(sh.week_start, sa.week_start) as week_start,
        coalesce(sh.units_shipped, 0) as units_shipped,
        coalesce(sa.units_sold, 0) as units_sold
    from weekly_shipments sh
    full outer join weekly_sales sa
        on sh.retailer_id = sa.retailer_id
        and sh.product_id = sa.product_id
        and sh.week_start = sa.week_start
)

select
    {{ dbt_utils.generate_surrogate_key(['retailer_id', 'product_id', 'week_start']) }} as reconciliation_sk,
    retailer_id,
    product_id,
    week_start,
    units_shipped,
    units_sold,
    (units_shipped - units_sold) as variance_units,
    case when units_sold > 0
        then round((units_shipped - units_sold)::numeric / units_sold, 3)
    end as variance_pct,
    case
        when units_shipped = 0 and units_sold > 0 then 'MISSING_SHIPMENT_DATA_OR_REPORTING_DELAY'
        when units_sold = 0 and units_shipped > 0 then 'MISSING_POS_DATA_OR_REPORTING_DELAY'
        when units_shipped > units_sold * 1.3 then 'SHIPMENTS_OUTPACING_SALES_INVENTORY_BUILDUP'
        when units_sold > units_shipped * 1.3 then 'SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT'
        else 'ALIGNED'
    end as reconciliation_signal
from combined
