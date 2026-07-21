{{ config(materialized='table') }}

-- Grain: channel_type x sale_date. Daily sales rolled up by channel type
-- (Physical Retail / Omnichannel-pickup-delivery / Marketplace / E-commerce),
-- the basis for the dashboard's physical-vs-e-commerce comparison and the
-- e-commerce-sales-share business metric (docs/metrics.md).

select
    channel_type,
    sale_date,
    date_trunc('month', sale_date)::date as month_start,
    sum(units_sold) as units_sold,
    sum(net_sales) as net_sales,
    count(distinct product_id) as distinct_products_sold,
    count(distinct retailer_id) as distinct_retailers
from {{ ref('int_product_daily_sales') }}
group by 1, 2, 3
