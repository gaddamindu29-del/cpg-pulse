{{ config(materialized='table') }}

select
    {{ dbt_utils.generate_surrogate_key(['distribution_center_id']) }} as distribution_center_sk,
    distribution_center_id,
    dc_name,
    region
from {{ ref('stg_distribution_centers') }}
