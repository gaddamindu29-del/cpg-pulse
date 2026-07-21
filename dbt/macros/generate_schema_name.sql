{#
    dbt's default generate_schema_name macro concatenates the target schema
    with a model's custom schema config (e.g. target=marts + custom=staging
    -> "marts_staging"), which is standard dbt behavior but reads oddly for
    this project's layer names. Override it so a model's `+schema:` config
    (set per-folder in dbt_project.yml: staging/intermediate/marts) IS the
    schema, full stop -- so `dbt/models/marts/facts/fact_retail_sales.sql`
    lands in `marts.fact_retail_sales`, matching docs/architecture.md's
    schema names exactly.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
