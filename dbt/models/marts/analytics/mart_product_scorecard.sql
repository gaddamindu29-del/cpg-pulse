{{ config(materialized='table') }}

-- Grain: one row per (current) product. Full-history rollup -- see the
-- "trailing window" note in mart_retailer_scorecard.sql; applies here too.

with current_products as (
    select * from {{ ref('dim_product') }} where is_current
),

sales as (
    select
        product_id,
        sum(units_sold) as total_units_sold,
        sum(net_sales) as total_net_sales,
        count(distinct retailer_id) as distinct_retailers_carrying,
        count(distinct store_id) as distinct_stores_selling,
        min(transaction_date) as first_sale_date,
        max(transaction_date) as last_sale_date
    from {{ ref('fact_retail_sales') }}
    group by 1
),

ecommerce as (
    select product_id, sum(units_ordered) as dtc_units_ordered, sum(net_sales) as dtc_net_sales
    from {{ ref('fact_ecommerce_orders') }}
    where not return_flag
    group by 1
),

stockout as (
    select
        product_id,
        count(*) filter (where stockout_risk_level = 'HIGH') as high_stockout_risk_snapshots,
        count(*) as total_inventory_snapshots
    from {{ ref('mart_stockout_risk') }}
    group by 1
),

excess as (
    select product_id, count(*) filter (where excess_inventory_risk_level in ('EXCESS', 'CRITICAL')) as excess_inventory_snapshots
    from {{ ref('mart_excess_inventory_risk') }}
    group by 1
),

promotions as (
    select product_id, count(distinct promotion_id) as promotion_count
    from {{ ref('dim_promotion') }}
    group by 1
)

select
    p.product_sk,
    p.product_id,
    p.brand,
    p.category,
    p.subcategory,
    p.unit_cost,
    p.is_discontinued,
    coalesce(s.total_units_sold, 0) + coalesce(e.dtc_units_ordered, 0) as total_units_sold_all_channels,
    coalesce(s.total_net_sales, 0) + coalesce(e.dtc_net_sales, 0) as total_net_sales_all_channels,
    coalesce(s.distinct_retailers_carrying, 0) as distinct_retailers_carrying,
    coalesce(s.distinct_stores_selling, 0) as distinct_stores_selling,
    s.first_sale_date,
    s.last_sale_date,
    coalesce(st.high_stockout_risk_snapshots, 0) as high_stockout_risk_snapshots,
    coalesce(st.total_inventory_snapshots, 0) as total_inventory_snapshots,
    case when st.total_inventory_snapshots > 0
        then round(st.high_stockout_risk_snapshots::numeric / st.total_inventory_snapshots, 4)
    end as high_stockout_risk_rate,
    coalesce(ex.excess_inventory_snapshots, 0) as excess_inventory_snapshots,
    coalesce(pr.promotion_count, 0) as promotion_count
from current_products p
left join sales s on p.product_id = s.product_id
left join ecommerce e on p.product_id = e.product_id
left join stockout st on p.product_id = st.product_id
left join excess ex on p.product_id = ex.product_id
left join promotions pr on p.product_id = pr.product_id
