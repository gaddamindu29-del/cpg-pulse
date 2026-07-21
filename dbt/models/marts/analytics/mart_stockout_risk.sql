{{ config(materialized='table') }}

-- Grain: product_id x store_id x date (one row per fact_inventory_snapshot
-- row -- see int_daily_velocity.sql for why that's this dataset's date
-- cadence). docs/architecture.md "Stockout Risk Logic":
--
--   days_of_supply = available_units / average_daily_units_sold
--   HIGH risk:   days_of_supply < var('stockout_high_risk_days_of_supply')
--   MEDIUM risk: days_of_supply < var('stockout_medium_risk_days_of_supply')
--   LOW risk:    otherwise
--
-- Thresholds are dbt vars (dbt_project.yml), not hardcoded, so a supply
-- chain analyst can retune them without a code change. A product/store with
-- no recent sales gets NO_RECENT_DEMAND rather than a misleading "LOW risk"
-- (zero velocity would otherwise make days_of_supply undefined/infinite).

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
    i.on_order_units,
    i.available_units,
    v.avg_daily_units_sold,
    v.velocity_trend,
    case
        when v.avg_daily_units_sold > 0
            then round(i.available_units / v.avg_daily_units_sold, 1)
    end as days_of_supply,
    case
        when v.avg_daily_units_sold is null or v.avg_daily_units_sold = 0 then 'NO_RECENT_DEMAND'
        when i.available_units / v.avg_daily_units_sold < {{ var('stockout_high_risk_days_of_supply') }} then 'HIGH'
        when i.available_units / v.avg_daily_units_sold < {{ var('stockout_medium_risk_days_of_supply') }} then 'MEDIUM'
        else 'LOW'
    end as stockout_risk_level
from inventory i
left join velocity v
    on i.product_id = v.product_id
    and i.store_id = v.store_id
    and i.snapshot_date = v.snapshot_date
