{{ config(materialized='view') }}

-- Grain: product_id x store_id x snapshot_date (one row per
-- fact_inventory_snapshot row -- the driving grain for stockout/excess risk).
--
-- For each inventory snapshot, computes trailing daily sell-through velocity
-- over two adjacent 14-day windows: `units_recent` (the 14 days ending on the
-- snapshot date) and `units_prior` (the 14 days before that). Using a fixed
-- day-count denominator (14) rather than counting observed sale-days means a
-- day with no sale correctly counts as zero demand, without needing a full
-- date spine per product/store -- SUM over existing fact_retail_sales rows
-- divided by a constant is already "average over N calendar days including
-- zero-sale days."
--
-- `velocity_trend` from comparing the two windows is one of the "recent
-- sales trend" inputs docs/architecture.md's Excess Inventory Logic section
-- calls for.

with inventory_dates as (
    select distinct product_id, store_id, retailer_id, snapshot_date
    from {{ ref('fact_inventory_snapshot') }}
),

sales_in_windows as (
    select
        d.product_id,
        d.store_id,
        d.retailer_id,
        d.snapshot_date,
        sum(
            case when s.transaction_date > d.snapshot_date - interval '14 days'
                      and s.transaction_date <= d.snapshot_date
                 then s.units_sold else 0 end
        ) as units_recent,
        sum(
            case when s.transaction_date > d.snapshot_date - interval '28 days'
                      and s.transaction_date <= d.snapshot_date - interval '14 days'
                 then s.units_sold else 0 end
        ) as units_prior
    from inventory_dates d
    left join {{ ref('fact_retail_sales') }} s
        on s.product_id = d.product_id
        and s.store_id = d.store_id
        and s.transaction_date > d.snapshot_date - interval '28 days'
        and s.transaction_date <= d.snapshot_date
    group by 1, 2, 3, 4
)

select
    product_id,
    store_id,
    retailer_id,
    snapshot_date,
    units_recent,
    units_prior,
    round(units_recent / 14.0, 3) as avg_daily_units_sold,
    round(units_prior / 14.0, 3) as avg_daily_units_sold_prior,
    case
        when units_prior = 0 and units_recent = 0 then 'NO_DEMAND'
        when units_prior = 0 then 'NEW_DEMAND'
        when units_recent::numeric / units_prior >= 1.15 then 'ACCELERATING'
        when units_recent::numeric / units_prior <= 0.85 then 'DECLINING'
        else 'STABLE'
    end as velocity_trend
from sales_in_windows
