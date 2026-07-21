select
    shipment_id,
    retailer_id,
    distribution_center_id,
    product_id,
    shipment_date::date as shipment_date,
    units_shipped::int as units_shipped,
    shipment_status,
    estimated_delivery_date::date as estimated_delivery_date,
    actual_delivery_date::date as actual_delivery_date,
    case
        when actual_delivery_date is not null
            then (actual_delivery_date::date - estimated_delivery_date::date)
    end as delivery_variance_days
from {{ source('landing', 'manufacturer_shipments') }}
