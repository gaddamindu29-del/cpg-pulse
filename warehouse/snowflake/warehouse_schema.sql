-- CPG Pulse dimensional warehouse -- Snowflake DDL.
--
-- This is a direct translation of warehouse/postgres/warehouse_schema.sql,
-- which was validated column-for-column against a live Postgres 18 instance
-- during development (see docs/checklist.md). It has NOT been run against a
-- real Snowflake account -- this environment has none configured (see
-- docs/architecture.md section 7, "local-first, cloud-compatible"). In a
-- real cloud deployment, `dbt run --target cloud` (dbt/profiles.yml.example)
-- would create these tables directly from the same dbt models used locally;
-- this file exists as reviewable documentation of the target schema and as
-- a starting point for hand-provisioning ahead of a first dbt run.
--
-- Translation notes vs. the Postgres version:
--   TEXT              -> VARCHAR
--   NUMERIC(p, s)     -> NUMBER(p, s)
--   TIMESTAMP         -> TIMESTAMP_NTZ
--   BOOLEAN           -> BOOLEAN (same)
--   CHECK constraints -> kept for documentation; Snowflake does not enforce
--                        CHECK/PK/FK/UNIQUE constraints at write time (they
--                        are informational / used by the query optimizer),
--                        so the actual value/referential-integrity
--                        enforcement for a Snowflake deployment lives in the
--                        dbt tests (dbt/models/marts/**/*.yml), not the DDL.

CREATE DATABASE IF NOT EXISTS CPG_PULSE;
USE DATABASE CPG_PULSE;
CREATE SCHEMA IF NOT EXISTS MARTS;
CREATE SCHEMA IF NOT EXISTS SNAPSHOTS;
USE SCHEMA MARTS;

-- =========================================================================
-- Dimensions
-- =========================================================================

CREATE TABLE IF NOT EXISTS DIM_DATE (
    DATE_SK       NUMBER(8) PRIMARY KEY,          -- YYYYMMDD
    DATE          DATE NOT NULL,
    WEEK          NUMBER(2) NOT NULL,
    MONTH         NUMBER(2) NOT NULL,
    QUARTER       NUMBER(1) NOT NULL,
    YEAR          NUMBER(4) NOT NULL,
    DAY_OF_WEEK   VARCHAR NOT NULL,
    WEEKEND_FLAG  BOOLEAN NOT NULL,
    HOLIDAY_FLAG  BOOLEAN NOT NULL,
    HOLIDAY_NAME  VARCHAR
);

CREATE TABLE IF NOT EXISTS DIM_RETAILER ( -- SCD Type 1
    RETAILER_SK    VARCHAR PRIMARY KEY,
    RETAILER_ID    VARCHAR NOT NULL UNIQUE,
    RETAILER_NAME  VARCHAR NOT NULL,
    RETAILER_TYPE  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DIM_DISTRIBUTION_CENTER (
    DISTRIBUTION_CENTER_SK  VARCHAR PRIMARY KEY,
    DISTRIBUTION_CENTER_ID  VARCHAR NOT NULL UNIQUE,
    DC_NAME                 VARCHAR NOT NULL,
    REGION                  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DIM_SALES_CHANNEL (
    CHANNEL_SK    VARCHAR PRIMARY KEY,
    CHANNEL_CODE  VARCHAR NOT NULL UNIQUE,
    CHANNEL_NAME  VARCHAR NOT NULL,
    CHANNEL_TYPE  VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DIM_PROMOTION ( -- SCD Type 1
    PROMOTION_SK         VARCHAR PRIMARY KEY,
    PROMOTION_ID         VARCHAR NOT NULL UNIQUE,
    RETAILER_ID          VARCHAR NOT NULL,
    PRODUCT_ID           VARCHAR NOT NULL,
    PROMOTION_TYPE       VARCHAR NOT NULL,
    START_DATE           DATE NOT NULL,
    END_DATE             DATE NOT NULL,
    DURATION_DAYS        NUMBER(4) NOT NULL,
    REGULAR_PRICE        NUMBER(10, 2) NOT NULL,
    PROMOTIONAL_PRICE    NUMBER(10, 2) NOT NULL,
    DISCOUNT_PERCENTAGE  NUMBER(5, 2) NOT NULL,
    DISPLAY_TYPE         VARCHAR,
    MARKETING_SPEND      NUMBER(12, 2) NOT NULL
);

-- SCD Type 2 (dbt snapshot -> dbt/snapshots/dim_product_snapshot.sql).
-- Grain: one row per product per historical version.
CREATE TABLE IF NOT EXISTS DIM_PRODUCT (
    PRODUCT_SK            VARCHAR PRIMARY KEY,
    PRODUCT_ID            VARCHAR NOT NULL,
    UPC                   VARCHAR,
    BRAND                 VARCHAR NOT NULL,
    CATEGORY              VARCHAR NOT NULL,
    SUBCATEGORY           VARCHAR NOT NULL,
    PRODUCT_NAME          VARCHAR NOT NULL,
    FLAVOR                VARCHAR,
    PACKAGE_SIZE          VARCHAR,
    CASE_QUANTITY         NUMBER(5),
    UNIT_COST             NUMBER(10, 2) NOT NULL,
    LAUNCH_DATE           DATE,
    DISCONTINUED_DATE     DATE,
    IS_DISCONTINUED       BOOLEAN NOT NULL,
    EFFECTIVE_START_DATE  TIMESTAMP_NTZ NOT NULL,
    EFFECTIVE_END_DATE    TIMESTAMP_NTZ,
    IS_CURRENT            BOOLEAN NOT NULL
);

-- SCD Type 2 (dbt snapshot -> dbt/snapshots/dim_store_snapshot.sql).
-- Grain: one row per store per historical version.
CREATE TABLE IF NOT EXISTS DIM_STORE (
    STORE_SK              VARCHAR PRIMARY KEY,
    STORE_ID              VARCHAR NOT NULL,
    RETAILER_ID           VARCHAR NOT NULL,
    STORE_NAME            VARCHAR NOT NULL,
    CITY                  VARCHAR,
    STATE                 VARCHAR,
    REGION                VARCHAR NOT NULL,
    STORE_FORMAT          VARCHAR NOT NULL,
    LATITUDE              NUMBER(9, 5),
    LONGITUDE             NUMBER(9, 5),
    OPENING_DATE          DATE,
    CLOSING_DATE          DATE,
    IS_CLOSED             BOOLEAN NOT NULL,
    EFFECTIVE_START_DATE  TIMESTAMP_NTZ NOT NULL,
    EFFECTIVE_END_DATE    TIMESTAMP_NTZ,
    IS_CURRENT            BOOLEAN NOT NULL
);

-- SCD Type 2, natively from source-provided effective dates (not a dbt
-- snapshot -- see dbt/models/marts/dimensions/dim_retailer_product_mapping.sql).
CREATE TABLE IF NOT EXISTS DIM_RETAILER_PRODUCT_MAPPING (
    RETAILER_PRODUCT_MAPPING_SK   VARCHAR PRIMARY KEY,
    RETAILER_ID                   VARCHAR NOT NULL,
    RETAILER_PRODUCT_ID           VARCHAR NOT NULL,
    RETAILER_PRODUCT_DESCRIPTION  VARCHAR,
    PRODUCT_ID                    VARCHAR NOT NULL,
    MATCH_METHOD                  VARCHAR NOT NULL,
    MATCH_CONFIDENCE              NUMBER(4, 3) NOT NULL,
    EFFECTIVE_START_DATE          DATE NOT NULL,
    EFFECTIVE_END_DATE            DATE,
    IS_CURRENT                    BOOLEAN NOT NULL
);

-- =========================================================================
-- Facts
-- =========================================================================

-- Grain: retailer x store x retailer_product x transaction_date x sales_channel.
CREATE TABLE IF NOT EXISTS FACT_RETAIL_SALES (
    SALES_SK VARCHAR PRIMARY KEY,
    PRODUCT_SK VARCHAR REFERENCES DIM_PRODUCT (PRODUCT_SK),
    STORE_SK VARCHAR REFERENCES DIM_STORE (STORE_SK),
    RETAILER_SK VARCHAR REFERENCES DIM_RETAILER (RETAILER_SK),
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK),
    CHANNEL_SK VARCHAR REFERENCES DIM_SALES_CHANNEL (CHANNEL_SK),
    RETAILER_ID VARCHAR NOT NULL,
    STORE_ID VARCHAR NOT NULL,
    RETAILER_PRODUCT_ID VARCHAR NOT NULL,
    PRODUCT_ID VARCHAR NOT NULL,
    TRANSACTION_DATE DATE NOT NULL,
    SALES_CHANNEL VARCHAR NOT NULL,
    UNITS_SOLD NUMBER(10) NOT NULL,
    GROSS_SALES NUMBER(12, 2) NOT NULL,
    DISCOUNT_AMOUNT NUMBER(12, 2) NOT NULL DEFAULT 0,
    NET_SALES NUMBER(12, 2) NOT NULL,
    REGULAR_PRICE NUMBER(10, 2) NOT NULL,
    SELLING_PRICE NUMBER(10, 2) NOT NULL
);

-- Grain: retailer x store x retailer_product x snapshot_date.
CREATE TABLE IF NOT EXISTS FACT_INVENTORY_SNAPSHOT (
    INVENTORY_SK VARCHAR PRIMARY KEY,
    PRODUCT_SK VARCHAR REFERENCES DIM_PRODUCT (PRODUCT_SK),
    STORE_SK VARCHAR REFERENCES DIM_STORE (STORE_SK),
    RETAILER_SK VARCHAR REFERENCES DIM_RETAILER (RETAILER_SK),
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK),
    RETAILER_ID VARCHAR NOT NULL,
    STORE_ID VARCHAR NOT NULL,
    RETAILER_PRODUCT_ID VARCHAR NOT NULL,
    PRODUCT_ID VARCHAR NOT NULL,
    SNAPSHOT_DATE DATE NOT NULL,
    ON_HAND_UNITS NUMBER(10) NOT NULL,
    ON_ORDER_UNITS NUMBER(10) NOT NULL DEFAULT 0,
    RESERVED_UNITS NUMBER(10) NOT NULL DEFAULT 0,
    AVAILABLE_UNITS NUMBER(10) NOT NULL
);

-- Grain: one row per manufacturer shipment line.
CREATE TABLE IF NOT EXISTS FACT_SHIPMENTS (
    SHIPMENT_ID VARCHAR PRIMARY KEY,
    PRODUCT_SK VARCHAR REFERENCES DIM_PRODUCT (PRODUCT_SK),
    RETAILER_SK VARCHAR REFERENCES DIM_RETAILER (RETAILER_SK),
    DISTRIBUTION_CENTER_SK VARCHAR REFERENCES DIM_DISTRIBUTION_CENTER (DISTRIBUTION_CENTER_SK),
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK),
    RETAILER_ID VARCHAR NOT NULL,
    DISTRIBUTION_CENTER_ID VARCHAR NOT NULL,
    PRODUCT_ID VARCHAR NOT NULL,
    SHIPMENT_DATE DATE NOT NULL,
    UNITS_SHIPPED NUMBER(10) NOT NULL,
    SHIPMENT_STATUS VARCHAR NOT NULL,
    ESTIMATED_DELIVERY_DATE DATE NOT NULL,
    ACTUAL_DELIVERY_DATE DATE,
    DELIVERY_VARIANCE_DAYS NUMBER(5)
);

-- Grain: retailer x product x promotion x activity_date (promotion span
-- exploded to one row per active day).
CREATE TABLE IF NOT EXISTS FACT_PROMOTIONS (
    PROMOTION_ACTIVITY_SK VARCHAR PRIMARY KEY,
    PROMOTION_SK VARCHAR REFERENCES DIM_PROMOTION (PROMOTION_SK),
    PRODUCT_SK VARCHAR REFERENCES DIM_PRODUCT (PRODUCT_SK),
    RETAILER_SK VARCHAR REFERENCES DIM_RETAILER (RETAILER_SK),
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK),
    PROMOTION_ID VARCHAR NOT NULL,
    RETAILER_ID VARCHAR NOT NULL,
    PRODUCT_ID VARCHAR NOT NULL,
    ACTIVITY_DATE DATE NOT NULL,
    PROMOTION_TYPE VARCHAR NOT NULL,
    DISPLAY_TYPE VARCHAR,
    REGULAR_PRICE NUMBER(10, 2) NOT NULL,
    PROMOTIONAL_PRICE NUMBER(10, 2) NOT NULL,
    DISCOUNT_PERCENTAGE NUMBER(5, 2) NOT NULL,
    MARKETING_SPEND_PER_DAY NUMBER(12, 2) NOT NULL
);

-- Grain: order_id x product_id.
CREATE TABLE IF NOT EXISTS FACT_ECOMMERCE_ORDERS (
    ECOMMERCE_ORDER_SK VARCHAR PRIMARY KEY,
    PRODUCT_SK VARCHAR REFERENCES DIM_PRODUCT (PRODUCT_SK),
    CHANNEL_SK VARCHAR REFERENCES DIM_SALES_CHANNEL (CHANNEL_SK),
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK),
    ORDER_ID VARCHAR NOT NULL,
    ORDER_DATE DATE NOT NULL,
    CUSTOMER_ID VARCHAR NOT NULL,
    PRODUCT_ID VARCHAR NOT NULL,
    UNITS_ORDERED NUMBER(10) NOT NULL,
    UNIT_PRICE NUMBER(10, 2) NOT NULL,
    DISCOUNT_AMOUNT NUMBER(12, 2) NOT NULL DEFAULT 0,
    NET_SALES NUMBER(12, 2) NOT NULL,
    ORDER_STATUS VARCHAR NOT NULL,
    FULFILLMENT_TYPE VARCHAR,
    RETURN_FLAG BOOLEAN NOT NULL DEFAULT FALSE
);

-- Grain: one row per data-quality check execution. Operational fact -- no
-- conformed dimension joins.
CREATE TABLE IF NOT EXISTS FACT_DATA_QUALITY_RESULTS (
    DQ_RESULT_ID VARCHAR PRIMARY KEY,
    RUN_ID VARCHAR NOT NULL,
    TABLE_NAME VARCHAR NOT NULL,
    CHECK_NAME VARCHAR NOT NULL,
    CHECK_CATEGORY VARCHAR NOT NULL,
    PASSED BOOLEAN NOT NULL,
    RECORDS_CHECKED NUMBER(15) NOT NULL DEFAULT 0,
    RECORDS_FAILED NUMBER(15) NOT NULL DEFAULT 0,
    FAILURE_RATE NUMBER(6, 4) NOT NULL DEFAULT 0,
    FAILURE_DETAIL VARCHAR,
    EXECUTED_AT TIMESTAMP_NTZ NOT NULL,
    DATE_SK NUMBER(8) REFERENCES DIM_DATE (DATE_SK)
);

-- Snowflake automatically maintains micro-partition pruning metadata, so
-- explicit indexes (as in the Postgres version) aren't applicable. A
-- CLUSTER BY on the most commonly filtered column is the Snowflake
-- equivalent for very large fact tables -- not applied here since this
-- dataset's volume doesn't warrant it (see docs/architecture.md section 14,
-- "Cost-Conscious Design Decisions").
-- ALTER TABLE FACT_RETAIL_SALES CLUSTER BY (TRANSACTION_DATE);
