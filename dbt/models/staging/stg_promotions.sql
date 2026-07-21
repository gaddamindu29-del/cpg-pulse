select
    promotion_id,
    retailer_id,
    product_id,
    promotion_type,
    start_date::date as start_date,
    end_date::date as end_date,
    regular_price::numeric(10, 2) as regular_price,
    promotional_price::numeric(10, 2) as promotional_price,
    discount_percentage::numeric(5, 2) as discount_percentage,
    display_type,
    marketing_spend::numeric(12, 2) as marketing_spend
from {{ source('landing', 'promotions') }}
