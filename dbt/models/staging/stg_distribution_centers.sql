select
    distribution_center_id,
    dc_name,
    region
from {{ source('landing', 'distribution_centers') }}
