{{ config(materialized='view') }}

-- Grain: one row per promotion_id. Estimates each promotion's "baseline"
-- daily sell-through -- what the product would likely have sold on an
-- average day with no promotion running -- by averaging actual POS sales
-- over the `promotion_baseline_lookback_weeks` (dbt_project.yml var, default
-- 8 weeks) immediately before the promotion started, EXCLUDING any day that
-- fell inside another promotion's active window for that same retailer +
-- product (otherwise a recent, unrelated promotion would inflate the
-- baseline and understate this promotion's lift).
--
-- This is the same "average of comparable non-promotional weeks" approach
-- docs/architecture.md's Promotion Effectiveness Logic section describes,
-- and mart_promotion_effectiveness.sql explicitly documents it as an
-- analytical estimate, not causal inference -- there is no control group,
-- so pre-period demand is the best available proxy for counterfactual demand.
--
-- Postgres-specific: `generate_series` in a LATERAL join explodes each
-- promotion's own baseline window row-wise. A Snowflake deployment would
-- need this rewritten against a date dimension cross join with a range
-- filter, or a JavaScript UDTF -- Snowflake's table generator functions
-- don't support this exact per-row date-range pattern.

with promos as (
    select promotion_id, retailer_id, product_id, start_date, end_date, duration_days
    from {{ ref('dim_promotion') }}
),

promo_activity_dates as (
    select distinct retailer_id, product_id, activity_date
    from {{ ref('fact_promotions') }}
),

baseline_window as (
    select
        p.promotion_id,
        p.retailer_id,
        p.product_id,
        d.candidate_date::date as candidate_date
    from promos p
    cross join lateral generate_series(
        p.start_date - ({{ var('promotion_baseline_lookback_weeks') }} * 7),
        p.start_date - 1,
        interval '1 day'
    ) as d(candidate_date)
),

baseline_window_clean as (
    select bw.promotion_id, bw.retailer_id, bw.product_id, bw.candidate_date
    from baseline_window bw
    left join promo_activity_dates pad
        on pad.retailer_id = bw.retailer_id
        and pad.product_id = bw.product_id
        and pad.activity_date = bw.candidate_date
    where pad.activity_date is null
),

baseline_sales as (
    select
        bwc.promotion_id,
        count(distinct bwc.candidate_date) as baseline_days,
        sum(coalesce(s.units_sold, 0)) as baseline_total_units
    from baseline_window_clean bwc
    left join {{ ref('fact_retail_sales') }} s
        on s.retailer_id = bwc.retailer_id
        and s.product_id = bwc.product_id
        and s.transaction_date = bwc.candidate_date
    group by bwc.promotion_id
)

select
    promotion_id,
    baseline_days,
    baseline_total_units,
    case when baseline_days > 0 then round(baseline_total_units::numeric / baseline_days, 3) end as baseline_avg_daily_units
from baseline_sales
