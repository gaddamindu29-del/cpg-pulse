-- CPG Pulse pipeline metadata schema (PostgreSQL).
--
-- This schema is used in BOTH environments (local and cloud): it is the
-- system of record for orchestration state -- watermarks, run history, DQ
-- results, schema-change events, and quarantine logging -- regardless of
-- whether the warehouse itself is Postgres (local) or Snowflake (cloud). See
-- docs/architecture.md section 4 ("Layer responsibilities") and section 12
-- ("Monitoring Strategy").

CREATE SCHEMA IF NOT EXISTS pipeline_meta;

-- One row per (source, environment): the last successfully processed
-- business date / ingestion timestamp. Ingestion only pulls data newer than
-- this watermark (docs/architecture.md section 10, "Incremental Loading").
CREATE TABLE IF NOT EXISTS pipeline_meta.watermarks (
    source_name         TEXT NOT NULL,
    environment          TEXT NOT NULL DEFAULT 'local',
    last_business_date   DATE,
    last_ingested_at     TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, environment)
);

-- One row per pipeline task execution (ingestion, Spark standardization, DQ
-- validation, dbt run, ...). Backs the /pipeline-runs API endpoint and the
-- dashboard's Ops page. docs/architecture.md section 12 ("Monitoring Strategy").
CREATE TABLE IF NOT EXISTS pipeline_meta.pipeline_runs (
    run_id              UUID PRIMARY KEY,
    dag_id               TEXT NOT NULL,
    task_id               TEXT NOT NULL,
    source_name           TEXT,
    run_type              TEXT NOT NULL CHECK (run_type IN (
                               'INGESTION', 'STANDARDIZATION', 'DATA_QUALITY',
                               'WAREHOUSE_LOAD', 'DBT_RUN', 'CURATED_METRICS',
                               'BACKFILL', 'DASHBOARD_REFRESH'
                           )),
    business_date         DATE,
    started_at            TIMESTAMPTZ NOT NULL,
    ended_at              TIMESTAMPTZ,
    duration_seconds      NUMERIC GENERATED ALWAYS AS (
                               EXTRACT(EPOCH FROM (ended_at - started_at))
                           ) STORED,
    status                TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
    records_read          BIGINT DEFAULT 0,
    records_valid         BIGINT DEFAULT 0,
    records_rejected      BIGINT DEFAULT 0,
    records_inserted      BIGINT DEFAULT 0,
    records_updated       BIGINT DEFAULT 0,
    retry_count           INT DEFAULT 0,
    source_file_count     INT DEFAULT 0,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source_started
    ON pipeline_meta.pipeline_runs (source_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON pipeline_meta.pipeline_runs (status);

-- One row per data-quality check execution. This table IS the source for
-- fact_data_quality_results in the warehouse (docs/architecture.md section 8).
CREATE TABLE IF NOT EXISTS pipeline_meta.dq_results (
    dq_result_id         UUID PRIMARY KEY,
    run_id                UUID NOT NULL REFERENCES pipeline_meta.pipeline_runs (run_id),
    table_name            TEXT NOT NULL,
    check_name            TEXT NOT NULL,
    check_category        TEXT NOT NULL CHECK (check_category IN (
                               'SCHEMA', 'NULL_CHECK', 'RANGE_CHECK', 'UNIQUENESS',
                               'REFERENTIAL_INTEGRITY', 'FRESHNESS', 'VOLUME_ANOMALY',
                               'ACCEPTED_VALUES', 'BUSINESS_RULE'
                           )),
    passed                BOOLEAN NOT NULL,
    records_checked       BIGINT,
    records_failed        BIGINT,
    failure_detail        TEXT,
    executed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dq_results_run ON pipeline_meta.dq_results (run_id);
CREATE INDEX IF NOT EXISTS idx_dq_results_table_executed
    ON pipeline_meta.dq_results (table_name, executed_at DESC);

-- Schema-change log: every time ingestion detects the incoming file schema
-- differs from the last-known schema for a source. docs/architecture.md
-- section 11 ("Schema evolution").
CREATE TABLE IF NOT EXISTS pipeline_meta.schema_change_log (
    schema_change_id     UUID PRIMARY KEY,
    source_name           TEXT NOT NULL,
    detected_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_type           TEXT NOT NULL CHECK (change_type IN (
                               'COLUMN_ADDED', 'COLUMN_REMOVED', 'COLUMN_RENAMED', 'TYPE_CHANGED'
                           )),
    is_breaking           BOOLEAN NOT NULL,
    column_name           TEXT,
    old_value             TEXT,
    new_value             TEXT,
    source_file           TEXT,
    run_id                UUID REFERENCES pipeline_meta.pipeline_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_schema_change_source
    ON pipeline_meta.schema_change_log (source_name, detected_at DESC);

-- Quarantine log: index of rejected records (the actual rejected rows live in
-- the data lake quarantine/ layer as files; this table is the queryable index
-- over them). docs/architecture.md section 11 ("Error Handling").
CREATE TABLE IF NOT EXISTS pipeline_meta.quarantine_log (
    quarantine_id         UUID PRIMARY KEY,
    run_id                UUID REFERENCES pipeline_meta.pipeline_runs (run_id),
    source_name           TEXT NOT NULL,
    business_date         DATE,
    rejection_reason      TEXT NOT NULL,
    record_count          BIGINT NOT NULL,
    quarantine_file_path  TEXT NOT NULL,
    replayed               BOOLEAN NOT NULL DEFAULT false,
    replayed_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_source_date
    ON pipeline_meta.quarantine_log (source_name, business_date);
