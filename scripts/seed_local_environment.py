#!/usr/bin/env python
"""Idempotent local-environment bootstrap.

`docker compose up` already creates the Postgres databases, applies the
metadata schema, and creates the MinIO buckets on first boot (see
infrastructure/postgres-init/ and the minio-init service in
docker-compose.yml). This script exists for two situations that init-on-boot
doesn't cover:

1. You changed warehouse/postgres/metadata_schema.sql after the Postgres
   volume already existed (docker-entrypoint-initdb.d only runs once, against
   an empty data directory) -- re-run this to apply the change.
2. You want to verify the environment is healthy without digging through
   `docker compose logs`.

Everything here is safe to run repeatedly: the schema DDL uses
`CREATE ... IF NOT EXISTS` throughout, and bucket creation is a no-op if the
bucket already exists.

Usage:
    python scripts/seed_local_environment.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("seed_local_environment")

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    example_path = REPO_ROOT / ".env.example"
    if not env_path.exists():
        if not example_path.exists():
            raise SystemExit(".env.example is missing -- cannot bootstrap defaults.")
        env_path.write_text(example_path.read_text())
        logger.warning("No .env found -- created one from .env.example with local-dev defaults.")

    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit("python-dotenv is required: pip install -r requirements.txt")
    load_dotenv(env_path)


def wait_for_postgres(max_attempts: int = 20, delay_seconds: float = 3.0) -> "psycopg2.extensions.connection":
    import psycopg2

    host = os.environ.get("METADATA_DB_HOST", "localhost")
    port = int(os.environ.get("METADATA_DB_PORT", "5432"))
    dbname = os.environ.get("METADATA_DB_NAME", "cpg_pulse_metadata")
    user = os.environ.get("METADATA_DB_USER", "cpgpulse")
    password = os.environ.get("METADATA_DB_PASSWORD", "cpgpulse_dev_password")

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
            logger.info("Connected to metadata Postgres at %s:%s/%s", host, port, dbname)
            return conn
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: we're polling for readiness
            last_error = exc
            logger.info("Postgres not ready yet (attempt %d/%d): %s", attempt, max_attempts, exc)
            time.sleep(delay_seconds)
    raise SystemExit(f"Could not connect to Postgres after {max_attempts} attempts: {last_error}")


def apply_metadata_schema(conn) -> None:
    schema_sql = (REPO_ROOT / "warehouse" / "postgres" / "metadata_schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    logger.info("Applied warehouse/postgres/metadata_schema.sql (idempotent).")


def ensure_minio_buckets() -> None:
    import boto3
    from botocore.exceptions import ClientError

    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "cpgpulse"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "cpgpulse_dev_secret"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    buckets = [
        os.environ.get("S3_BUCKET_RAW", "cpg-pulse-raw"),
        os.environ.get("S3_BUCKET_STANDARDIZED", "cpg-pulse-standardized"),
        os.environ.get("S3_BUCKET_CURATED", "cpg-pulse-curated"),
        os.environ.get("S3_BUCKET_QUARANTINE", "cpg-pulse-quarantine"),
    ]
    for bucket in buckets:
        try:
            client.head_bucket(Bucket=bucket)
            logger.info("Bucket already exists: %s", bucket)
        except ClientError:
            client.create_bucket(Bucket=bucket)
            logger.info("Created bucket: %s", bucket)


def main() -> None:
    load_env()
    conn = wait_for_postgres()
    try:
        apply_metadata_schema(conn)
    finally:
        conn.close()

    try:
        ensure_minio_buckets()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reach MinIO at %s (%s) -- is `docker compose up` running?", os.environ.get("AWS_ENDPOINT_URL"), exc)
        sys.exit(1)

    logger.info(
        "Local environment ready. Next: `python scripts/generate_synthetic_data.py` to produce sample data, "
        "then see docs/runbook.md for the ingestion -> dbt -> API -> dashboard walkthrough."
    )


if __name__ == "__main__":
    main()
