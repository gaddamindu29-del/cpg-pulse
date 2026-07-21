{#
    SCD Type 2 history for stores. Tracks the attributes that actually change
    over a store's life and matter for trend analysis (region reassignment,
    format conversion/remodel, closure) -- not cosmetic fields like store_name.

    Selects from stg_store_master (not the raw source directly) so the
    snapshot inherits staging's type casts (opening_date/closing_date ::date)
    -- see dim_product_snapshot.sql's header comment for why this matters.
#}
{% snapshot dim_store_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='store_id',
        strategy='check',
        check_cols=['region', 'store_format', 'closing_date'],
    )
}}

select
    store_id,
    retailer_id,
    store_name,
    city,
    state,
    region,
    store_format,
    latitude,
    longitude,
    opening_date,
    closing_date
from {{ ref('stg_store_master') }}

{% endsnapshot %}
