{{ config(materialized='table') }}

-- Grain: one row per retailer. Full-history rollup (this is a portfolio-
-- scale, mostly-static dataset -- a production version would parameterize
-- this to a trailing window, e.g. "trailing 90 days," via an incremental or
-- date-filtered variant). Combines sales performance, inventory risk
-- exposure, and promotion activity into one retailer-level view for the
-- dashboard's retailer comparison and the /retailers/{id}/performance API
-- endpoint.

with sales as (
    select
        retailer_id,
        sum(units_sold) as total_units_sold,
        sum(gross_sales) as total_gross_sales,
        sum(net_sales) as total_net_sales,
        count(distinct product_id) as distinct_products_sold,
        count(distinct store_id) as distinct_stores,
        min(transaction_date) as first_sale_date,
        max(transaction_date) as last_sale_date
    from {{ ref('fact_retail_sales') }}
    group by 1
),

stockout as (
    select
        retailer_id,
        count(*) filter (where stockout_risk_level = 'HIGH') as high_stockout_risk_snapshots,
        count(*) as total_inventory_snapshots
    from {{ ref('mart_stockout_risk') }}
    group by 1
),

excess as (
    select
        retailer_id,
        count(*) filter (where excess_inventory_risk_level in ('EXCESS', 'CRITICAL')) as excess_inventory_snapshots
    from {{ ref('mart_excess_inventory_risk') }}
    group by 1
),

promo_activity as (
    select retailer_id, count(distinct promotion_id) as promotion_count, sum(marketing_spend) as total_marketing_spend
    from {{ ref('dim_promotion') }}
    group by 1
)

select
    r.retailer_sk,
    r.retailer_id,
    r.retailer_name,
    r.retailer_type,
    coalesce(s.total_units_sold, 0) as total_units_sold,
    coalesce(s.total_gross_sales, 0) as total_gross_sales,
    coalesce(s.total_net_sales, 0) as total_net_sales,
    case when s.total_gross_sales > 0
        then round(s.total_net_sales / s.total_gross_sales, 4)
    end as net_to_gross_ratio,
    coalesce(s.distinct_products_sold, 0) as distinct_products_sold,
    coalesce(s.distinct_stores, 0) as distinct_stores,
    s.first_sale_date,
    s.last_sale_date,
    coalesce(so.high_stockout_risk_snapshots, 0) as high_stockout_risk_snapshots,
    coalesce(so.total_inventory_snapshots, 0) as total_inventory_snapshots,
    case when so.total_inventory_snapshots > 0
        then round(so.high_stockout_risk_snapshots::numeric / so.total_inventory_snapshots, 4)
    end as high_stockout_risk_rate,
    coalesce(ex.excess_inventory_snapshots, 0) as excess_inventory_snapshots,
    coalesce(pa.promotion_count, 0) as promotion_count,
    coalesce(pa.total_marketing_spend, 0) as total_marketing_spend
from {{ ref('dim_retailer') }} r
left join sales s on r.retailer_id = s.retailer_id
left join stockout so on r.retailer_id = so.retailer_id
left join excess ex on r.retailer_id = ex.retailer_id
left join promo_activity pa on r.retailer_id = pa.retailer_id
