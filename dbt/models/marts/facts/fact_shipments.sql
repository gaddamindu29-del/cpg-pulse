{{
    config(
        materialized='incremental',
        unique_key='shipment_id',
        incremental_strategy='delete+insert',
    )
}}

-- Grain: one row per manufacturer shipment line (shipment_id).

with shipments as (
    select * from {{ ref('stg_manufacturer_shipments') }}
    {% if is_incremental() %}
    where shipment_date > (select coalesce(max(shipment_date), '1900-01-01') from {{ this }})
    {% endif %}
),

current_product as (
    select * from {{ ref('dim_product') }} where is_current
)

select
    sh.shipment_id,
    p.product_sk,
    r.retailer_sk,
    dc.distribution_center_sk,
    (to_char(sh.shipment_date, 'YYYYMMDD'))::int as date_sk,
    sh.retailer_id,
    sh.distribution_center_id,
    sh.product_id,
    sh.shipment_date,
    sh.units_shipped,
    sh.shipment_status,
    sh.estimated_delivery_date,
    sh.actual_delivery_date,
    sh.delivery_variance_days
from shipments sh
left join current_product p on sh.product_id = p.product_id
left join {{ ref('dim_retailer') }} r on sh.retailer_id = r.retailer_id
left join {{ ref('dim_distribution_center') }} dc on sh.distribution_center_id = dc.distribution_center_id
