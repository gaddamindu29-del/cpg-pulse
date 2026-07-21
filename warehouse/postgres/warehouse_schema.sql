-- CPG Pulse dimensional warehouse -- PostgreSQL reference DDL.
--
-- In normal operation dbt builds and owns every table below (`dbt run` /
-- `dbt snapshot` against the `local` target -- see dbt/dbt_project.yml and
-- dbt/profiles.yml.example). This file is not executed as part of the
-- pipeline; it exists so the schema can be read, reviewed, and discussed
-- without running dbt, and it matches column-for-column what was verified
-- against a live Postgres 18 instance during development (see
-- docs/checklist.md Phase 5 notes). If you do want to hand-provision the
-- schema ahead of a first `dbt run` (not required -- dbt creates on demand),
-- this is safe to run standalone.
--
-- Schema layout: staging (views), snapshots (SCD2 history), marts
-- (facts + dimensions). See docs/architecture.md section 8 for grain
-- definitions and docs/data_dictionary.md for column-level business meaning.

CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS snapshots;

-- =========================================================================
-- Dimensions
-- =========================================================================

CREATE TABLE IF NOT EXISTS marts.dim_date (
    date_sk       INT PRIMARY KEY,               -- YYYYMMDD
    date          DATE NOT NULL,
    week          INT NOT NULL,
    month         INT NOT NULL,
    quarter       INT NOT NULL,
    year          INT NOT NULL,
    day_of_week   TEXT NOT NULL,
    weekend_flag  BOOLEAN NOT NULL,
    holiday_flag  BOOLEAN NOT NULL,
    holiday_name  TEXT
);

CREATE TABLE IF NOT EXISTS marts.dim_retailer (              -- SCD Type 1
    retailer_sk    TEXT PRIMARY KEY,
    retailer_id    TEXT NOT NULL UNIQUE,
    retailer_name  TEXT NOT NULL,
    retailer_type  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.dim_distribution_center (
    distribution_center_sk  TEXT PRIMARY KEY,
    distribution_center_id  TEXT NOT NULL UNIQUE,
    dc_name                 TEXT NOT NULL,
    region                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.dim_sales_channel (
    channel_sk    TEXT PRIMARY KEY,
    channel_code  TEXT NOT NULL UNIQUE,
    channel_name  TEXT NOT NULL,
    channel_type  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.dim_promotion (              -- SCD Type 1
    promotion_sk         TEXT PRIMARY KEY,
    promotion_id         TEXT NOT NULL UNIQUE,
    retailer_id          TEXT NOT NULL,
    product_id           TEXT NOT NULL,
    promotion_type       TEXT NOT NULL,
    start_date           DATE NOT NULL,
    end_date             DATE NOT NULL,
    duration_days        INT NOT NULL,
    regular_price        NUMERIC(10, 2) NOT NULL,
    promotional_price    NUMERIC(10, 2) NOT NULL,
    discount_percentage  NUMERIC(5, 2) NOT NULL,
    display_type         TEXT,
    marketing_spend      NUMERIC(12, 2) NOT NULL
);

-- SCD Type 2 (dbt snapshot -> dbt/snapshots/dim_product_snapshot.sql).
-- Grain: one row per product per historical version.
CREATE TABLE IF NOT EXISTS marts.dim_product (
    product_sk            TEXT PRIMARY KEY,
    product_id            TEXT NOT NULL,
    upc                   TEXT,
    brand                 TEXT NOT NULL,
    category              TEXT NOT NULL,
    subcategory           TEXT NOT NULL,
    product_name          TEXT NOT NULL,
    flavor                TEXT,
    package_size          TEXT,
    case_quantity         INT,
    unit_cost             NUMERIC(10, 2) NOT NULL,
    launch_date           DATE,
    discontinued_date     DATE,
    is_discontinued       BOOLEAN NOT NULL,
    effective_start_date  TIMESTAMP NOT NULL,
    effective_end_date    TIMESTAMP,
    is_current            BOOLEAN NOT NULL
);

-- SCD Type 2 (dbt snapshot -> dbt/snapshots/dim_store_snapshot.sql).
-- Grain: one row per store per historical version.
CREATE TABLE IF NOT EXISTS marts.dim_store (
    store_sk              TEXT PRIMARY KEY,
    store_id              TEXT NOT NULL,
    retailer_id           TEXT NOT NULL,
    store_name            TEXT NOT NULL,
    city                  TEXT,
    state                 TEXT,
    region                TEXT NOT NULL,
    store_format          TEXT NOT NULL,
    latitude              NUMERIC(9, 5),
    longitude             NUMERIC(9, 5),
    opening_date          DATE,
    closing_date          DATE,
    is_closed             BOOLEAN NOT NULL,
    effective_start_date  TIMESTAMP NOT NULL,
    effective_end_date    TIMESTAMP,
    is_current            BOOLEAN NOT NULL
);

-- SCD Type 2, natively from source-provided effective dates (NOT a dbt
-- snapshot -- see dbt/models/marts/dimensions/dim_retailer_product_mapping.sql
-- for why). Grain: one row per (retailer_id, retailer_product_id) per
-- historical mapping version.
CREATE TABLE IF NOT EXISTS marts.dim_retailer_product_mapping (
    retailer_product_mapping_sk   TEXT PRIMARY KEY,
    retailer_id                   TEXT NOT NULL,
    retailer_product_id           TEXT NOT NULL,
    retailer_product_description  TEXT,
    product_id                    TEXT NOT NULL,
    match_method                  TEXT NOT NULL,
    match_confidence      NUMERIC(4, 3) NOT NULL,
    effective_start_date  DATE NOT NULL,
    effective_end_date    DATE,
    is_current            BOOLEAN NOT NULL
);

-- =========================================================================
-- Facts
-- =========================================================================

-- Grain: retailer x store x retailer_product x transaction_date x sales_channel.
CREATE TABLE IF NOT EXISTS marts.fact_retail_sales (
    sales_sk TEXT PRIMARY KEY,
    product_sk TEXT REFERENCES marts.dim_product (product_sk),
    store_sk TEXT REFERENCES marts.dim_store (store_sk),
    retailer_sk TEXT REFERENCES marts.dim_retailer (retailer_sk),
    date_sk INT REFERENCES marts.dim_date (date_sk),
    channel_sk TEXT REFERENCES marts.dim_sales_channel (channel_sk),
    retailer_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    retailer_product_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    transaction_date DATE NOT NULL,
    sales_channel TEXT NOT NULL,
    units_sold INT NOT NULL CHECK (units_sold > 0),
    gross_sales NUMERIC(12, 2) NOT NULL,
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_sales NUMERIC(12, 2) NOT NULL CHECK (net_sales >= 0),
    regular_price NUMERIC(10, 2) NOT NULL,
    selling_price NUMERIC(10, 2) NOT NULL
);

-- Grain: retailer x store x retailer_product x snapshot_date.
CREATE TABLE IF NOT EXISTS marts.fact_inventory_snapshot (
    inventory_sk TEXT PRIMARY KEY,
    product_sk TEXT REFERENCES marts.dim_product (product_sk),
    store_sk TEXT REFERENCES marts.dim_store (store_sk),
    retailer_sk TEXT REFERENCES marts.dim_retailer (retailer_sk),
    date_sk INT REFERENCES marts.dim_date (date_sk),
    retailer_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    retailer_product_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    on_hand_units INT NOT NULL CHECK (on_hand_units >= 0),
    on_order_units INT NOT NULL DEFAULT 0,
    reserved_units INT NOT NULL DEFAULT 0,
    available_units INT NOT NULL CHECK (available_units >= 0)
);

-- Grain: one row per manufacturer shipment line.
CREATE TABLE IF NOT EXISTS marts.fact_shipments (
    shipment_id TEXT PRIMARY KEY,
    product_sk TEXT REFERENCES marts.dim_product (product_sk),
    retailer_sk TEXT REFERENCES marts.dim_retailer (retailer_sk),
    distribution_center_sk TEXT REFERENCES marts.dim_distribution_center (distribution_center_sk),
    date_sk INT REFERENCES marts.dim_date (date_sk),
    retailer_id TEXT NOT NULL,
    distribution_center_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    shipment_date DATE NOT NULL,
    units_shipped INT NOT NULL CHECK (units_shipped > 0),
    shipment_status TEXT NOT NULL,
    estimated_delivery_date DATE NOT NULL,
    actual_delivery_date DATE,
    delivery_variance_days INT
);

-- Grain: retailer x product x promotion x activity_date (promotion span
-- exploded to one row per active day).
CREATE TABLE IF NOT EXISTS marts.fact_promotions (
    promotion_activity_sk TEXT PRIMARY KEY,
    promotion_sk TEXT REFERENCES marts.dim_promotion (promotion_sk),
    product_sk TEXT REFERENCES marts.dim_product (product_sk),
    retailer_sk TEXT REFERENCES marts.dim_retailer (retailer_sk),
    date_sk INT REFERENCES marts.dim_date (date_sk),
    promotion_id TEXT NOT NULL,
    retailer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    activity_date DATE NOT NULL,
    promotion_type TEXT NOT NULL,
    display_type TEXT,
    regular_price NUMERIC(10, 2) NOT NULL,
    promotional_price NUMERIC(10, 2) NOT NULL,
    discount_percentage NUMERIC(5, 2) NOT NULL,
    marketing_spend_per_day NUMERIC(12, 2) NOT NULL
);

-- Grain: order_id x product_id.
CREATE TABLE IF NOT EXISTS marts.fact_ecommerce_orders (
    ecommerce_order_sk TEXT PRIMARY KEY,
    product_sk TEXT REFERENCES marts.dim_product (product_sk),
    channel_sk TEXT REFERENCES marts.dim_sales_channel (channel_sk),
    date_sk INT REFERENCES marts.dim_date (date_sk),
    order_id TEXT NOT NULL,
    order_date DATE NOT NULL,
    customer_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    units_ordered INT NOT NULL CHECK (units_ordered > 0),
    unit_price NUMERIC(10, 2) NOT NULL,
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_sales NUMERIC(12, 2) NOT NULL CHECK (net_sales >= 0),
    order_status TEXT NOT NULL,
    fulfillment_type TEXT,
    return_flag BOOLEAN NOT NULL DEFAULT false
);

-- Grain: one row per data-quality check execution. Operational fact -- no
-- conformed dimension joins (see docs/architecture.md section 8).
CREATE TABLE IF NOT EXISTS marts.fact_data_quality_results (
    dq_result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    check_name TEXT NOT NULL,
    check_category TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    records_checked BIGINT NOT NULL DEFAULT 0,
    records_failed BIGINT NOT NULL DEFAULT 0,
    failure_rate NUMERIC(6, 4) NOT NULL DEFAULT 0,
    failure_detail TEXT,
    executed_at TIMESTAMP NOT NULL,
    date_sk INT REFERENCES marts.dim_date (date_sk)
);

CREATE INDEX IF NOT EXISTS idx_fact_retail_sales_date ON marts.fact_retail_sales (transaction_date);
CREATE INDEX IF NOT EXISTS idx_fact_retail_sales_product ON marts.fact_retail_sales (product_id);
CREATE INDEX IF NOT EXISTS idx_fact_inventory_date ON marts.fact_inventory_snapshot (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_fact_shipments_date ON marts.fact_shipments (shipment_date);
CREATE INDEX IF NOT EXISTS idx_fact_promotions_date ON marts.fact_promotions (activity_date);
CREATE INDEX IF NOT EXISTS idx_fact_ecommerce_date ON marts.fact_ecommerce_orders (order_date);
