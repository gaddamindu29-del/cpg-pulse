{{ config(materialized='table') }}

-- Grain: one row per (retailer_id, retailer_product_id) per historical
-- mapping version. This is SCD Type 2 *without* a dbt snapshot: unlike
-- product_master/store_master (which only ever expose current-state
-- attributes), the retailer_product_mapping source already carries
-- effective_start_date/effective_end_date -- the generator (and, in a real
-- retailer integration, the retailer's own feed) tracks remapping history
-- itself. Wrapping this in a dbt snapshot would be redundant (and wrong: a
-- snapshot's history is anchored to *when dbt happened to run*, not to the
-- source's own effective dates). See docs/architecture.md section 8.
select
    {{ dbt_utils.generate_surrogate_key(['retailer_id', 'retailer_product_id', 'effective_start_date']) }} as retailer_product_mapping_sk,
    retailer_id,
    retailer_product_id,
    retailer_product_description,
    product_id,
    match_method,
    match_confidence,
    effective_start_date,
    effective_end_date,
    is_current
from {{ ref('stg_retailer_product_mapping') }}
