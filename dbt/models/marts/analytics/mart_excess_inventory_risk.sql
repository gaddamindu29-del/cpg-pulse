{{ config(materialized='table') }}

-- Grain: product_id x store_id x date. docs/architecture.md "Excess
-- Inventory Logic": flags a product/store as excess when days_of_supply
-- exceeds `var('excess_inventory_days_of_supply_threshold')` (default 45
-- days) -- i.e. it would take more than that many days to sell through
-- current available inventory at the recent sell-through rate. A DECLINING
-- velocity_trend (from int_daily_velocity) on top of high days_of_supply is
-- flagged as the more urgent CRITICAL case: not just "a lot of inventory,"
-- but "a lot of inventory *and* demand is falling further behind it."

with inventory as (
    select * from {{ ref('fact_inventory_snapshot') }}
),

velocity as (
    select * from {{ ref('int_daily_velocity') }}
)

select
    i.inventory_sk,
    i.product_sk,
    i.store_sk,
    i.retailer_sk,
    i.date_sk,
    i.retailer_id,
    i.store_id,
    i.product_id,
    i.snapshot_date,
    i.on_hand_units,
    i.available_units,
    v.avg_daily_units_sold,
    v.velocity_trend,
    case
        when v.avg_daily_units_sold > 0
            then round(i.available_units / v.avg_daily_units_sold, 1)
    end as days_of_supply,
    (
        v.avg_daily_units_sold > 0
        and (i.available_units / v.avg_daily_units_sold) > {{ var('excess_inventory_days_of_supply_threshold') }}
    ) as is_excess_inventory,
    case
        when v.avg_daily_units_sold > 0
             and (i.available_units / v.avg_daily_units_sold) > {{ var('excess_inventory_days_of_supply_threshold') }}
             and v.velocity_trend = 'DECLINING'
            then 'CRITICAL'
        when v.avg_daily_units_sold > 0
             and (i.available_units / v.avg_daily_units_sold) > {{ var('excess_inventory_days_of_supply_threshold') }}
            then 'EXCESS'
        when v.avg_daily_units_sold is null or v.avg_daily_units_sold = 0
            then 'NO_RECENT_DEMAND'
        else 'NORMAL'
    end as excess_inventory_risk_level
from inventory i
left join velocity v
    on i.product_id = v.product_id
    and i.store_id = v.store_id
    and i.snapshot_date = v.snapshot_date
