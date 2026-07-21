{#
    SCD Type 2 history for the product master. product_master is a
    full-snapshot source (no history of its own -- see
    dbt/models/staging/stg_product_master.sql); this snapshot is what turns
    "today's attributes" into "attribute history over time" by comparing each
    dbt run's load against the previous one and closing out changed rows.

    Selects from stg_product_master (not the raw source directly) so the
    snapshot inherits staging's type casts -- upc::text, launch_date::date,
    etc. A snapshot built straight off the raw source landed both of those
    wrong (upc came through as bigint from a CSV/pandas round-trip, and
    dates came through as full timestamps) until this was caught by the
    API's Pydantic response model rejecting the bigint.

    check_cols tracks the attributes a business user would actually care
    about the history of (brand/category changes are rare re-classifications;
    unit_cost changes matter for margin trend analysis; discontinued_date
    marks a product's lifecycle end). product_name/flavor/package_size are
    intentionally excluded -- they're presentation details, not what
    "Slowly Changing Dimension" is meant to capture here.
#}
{% snapshot dim_product_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='product_id',
        strategy='check',
        check_cols=['brand', 'category', 'subcategory', 'unit_cost', 'discontinued_date'],
    )
}}

select
    product_id,
    upc,
    brand,
    category,
    subcategory,
    product_name,
    flavor,
    package_size,
    case_quantity,
    unit_cost,
    launch_date,
    discontinued_date
from {{ ref('stg_product_master') }}

{% endsnapshot %}
