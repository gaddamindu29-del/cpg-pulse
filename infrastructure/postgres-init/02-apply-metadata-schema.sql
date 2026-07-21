-- Applies to $POSTGRES_DB (cpg_pulse_metadata) automatically, since psql
-- executes .sql files in docker-entrypoint-initdb.d against that database by
-- default. The real DDL lives in warehouse/postgres/metadata_schema.sql
-- (mounted read-only into the container) so there is a single source of truth
-- shared by this init script and any manual `psql -f` re-application.
\i /opt/warehouse-postgres/metadata_schema.sql
