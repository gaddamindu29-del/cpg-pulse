select
    retailer_id,
    retailer_name,
    retailer_type
from {{ source('landing', 'retailers') }}
