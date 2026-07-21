{{ config(materialized='table') }}

-- Grain: one row per promotion_id. docs/architecture.md "Promotion
-- Effectiveness Logic".
--
-- *** This is an analytical estimate, not a causal-inference model. ***
-- incremental_units = actual promo-period units - (baseline daily rate x
-- promo duration). The baseline (int_promotion_baseline.sql) is the average
-- of comparable non-promotional days immediately before the promotion,
-- excluding any day itself covered by another promotion. There is no
-- control group and no adjustment for concurrent external factors
-- (seasonality beyond what the pre-period happens to reflect, competitor
-- activity, macro trends) -- a real causal read would need a matched control
-- group (e.g. comparable stores/regions without the promotion) or a proper
-- experiment design. Treat lift_percentage and promotion_roi here as
-- directional estimates for prioritization, not precise financial figures.

with promos as (
    select * from {{ ref('dim_promotion') }}
),

baseline as (
    select * from {{ ref('int_promotion_baseline') }}
),

promo_sales as (
    select
        fp.promotion_id,
        sum(fs.units_sold) as promo_units_sold,
        sum(fs.net_sales) as promo_net_sales
    from {{ ref('fact_promotions') }} fp
    join {{ ref('fact_retail_sales') }} fs
        on fs.retailer_id = fp.retailer_id
        and fs.product_id = fp.product_id
        and fs.transaction_date = fp.activity_date
    group by fp.promotion_id
),

joined as (
    select
        p.promotion_sk,
        p.promotion_id,
        p.retailer_id,
        p.product_id,
        p.promotion_type,
        p.display_type,
        p.start_date,
        p.end_date,
        p.duration_days,
        p.regular_price,
        p.promotional_price,
        p.discount_percentage,
        p.marketing_spend,
        b.baseline_days,
        b.baseline_avg_daily_units,
        coalesce(b.baseline_avg_daily_units * p.duration_days, 0) as expected_baseline_units,
        coalesce(ps.promo_units_sold, 0) as actual_promo_units,
        coalesce(ps.promo_net_sales, 0) as actual_promo_net_sales
    from promos p
    left join baseline b on b.promotion_id = p.promotion_id
    left join promo_sales ps on ps.promotion_id = p.promotion_id
)

select
    *,
    (actual_promo_units - expected_baseline_units) as incremental_units,
    (actual_promo_units - expected_baseline_units) * promotional_price as incremental_revenue,
    (regular_price - promotional_price) * actual_promo_units as discount_cost,
    case
        when baseline_avg_daily_units is null then null  -- insufficient baseline data (e.g. a newly-launched product)
        when expected_baseline_units > 0
            then round(((actual_promo_units / expected_baseline_units) - 1) * 100, 1)
        when actual_promo_units > 0 then null  -- baseline was zero but promo sold units: lift is undefined (infinite), not zero
        else 0
    end as lift_percentage,
    case
        when ((regular_price - promotional_price) * actual_promo_units + marketing_spend) > 0
            then round(
                ((actual_promo_units - expected_baseline_units) * promotional_price)
                / ((regular_price - promotional_price) * actual_promo_units + marketing_spend)
            , 3)
    end as promotion_roi
from joined
