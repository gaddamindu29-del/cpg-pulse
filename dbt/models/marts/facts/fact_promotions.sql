{{ config(materialized='table') }}

-- Grain: one row per retailer x product x promotion x activity_date -- the
-- promotion's date range is exploded into one row per active day
-- (docs/architecture.md section 8), so this fact can be joined directly onto
-- fact_retail_sales on (retailer_id, product_id, date_sk) to flag "was a
-- promotion active on this sale's date." The lift/incrementality *estimate*
-- itself lives in dbt/models/intermediate/int_promotion_lift.sql -- this
-- fact only records promotion activity, not its estimated effect.

with promotions as (
    select * from {{ ref('dim_promotion') }}
),

activity_dates as (
    select
        p.promotion_sk,
        p.promotion_id,
        p.retailer_id,
        p.product_id,
        p.promotion_type,
        p.display_type,
        p.regular_price,
        p.promotional_price,
        p.discount_percentage,
        p.marketing_spend,
        d.date as activity_date
    from promotions p
    cross join lateral generate_series(p.start_date, p.end_date, interval '1 day') as d(date)
)

select
    {{ dbt_utils.generate_surrogate_key(['a.retailer_id', 'a.product_id', 'a.promotion_id', 'a.activity_date']) }} as promotion_activity_sk,
    a.promotion_sk,
    p.product_sk,
    r.retailer_sk,
    (to_char(a.activity_date, 'YYYYMMDD'))::int as date_sk,
    a.promotion_id,
    a.retailer_id,
    a.product_id,
    a.activity_date::date as activity_date,
    a.promotion_type,
    a.display_type,
    a.regular_price,
    a.promotional_price,
    a.discount_percentage,
    -- marketing spend is reported at the promotion level, not per day;
    -- amortize evenly across the promotion's active days so a daily-grain
    -- join doesn't double count total spend when aggregated.
    round(a.marketing_spend / greatest(1, count(*) over (partition by a.promotion_id)), 2) as marketing_spend_per_day
from activity_dates a
left join {{ ref('dim_product') }} p on a.product_id = p.product_id and p.is_current
left join {{ ref('dim_retailer') }} r on a.retailer_id = r.retailer_id
