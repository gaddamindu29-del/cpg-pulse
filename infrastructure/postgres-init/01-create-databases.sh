#!/bin/bash
# Runs automatically on first Postgres container init (docker-entrypoint-initdb.d).
# The postgres image already created $POSTGRES_DB (cpg_pulse_metadata, our
# pipeline metadata store). This script creates the two other databases that
# share the same Postgres instance in local dev: the local warehouse
# (dbt's local target, standing in for Snowflake -- see docs/architecture.md
# section 7) and Airflow's own application database.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE cpg_pulse_warehouse OWNER $POSTGRES_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cpg_pulse_warehouse')\gexec

    SELECT 'CREATE DATABASE airflow OWNER $POSTGRES_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
EOSQL
