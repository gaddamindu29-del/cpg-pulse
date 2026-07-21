select
    product_id,
    -- UPCs must stay text: they're identifiers, not numbers (leading zeros
    -- matter, no arithmetic is ever done on them). A plain `upc` column
    -- round-tripped through CSV -> pandas -> Postgres gets inferred as
    -- bigint because every value happens to look numeric -- caught when the
    -- API's Pydantic model (str) rejected the warehouse's actual int value.
    upc::text as upc,
    trim(brand) as brand,
    trim(category) as category,
    trim(subcategory) as subcategory,
    product_name,
    flavor,
    package_size,
    case_quantity::int as case_quantity,
    unit_cost::numeric(10, 2) as unit_cost,
    launch_date::date as launch_date,
    discontinued_date::date as discontinued_date,
    (discontinued_date is not null) as is_discontinued
from {{ source('landing', 'product_master') }}
