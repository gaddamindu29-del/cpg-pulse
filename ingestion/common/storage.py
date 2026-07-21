"""Lake storage abstraction: local filesystem by default, S3/MinIO when
configured. Every ingestion and Spark module goes through this so the exact
same code runs against a laptop's disk (zero-friction local dev, no Docker
required to test ingestion in isolation) or against S3/MinIO (the Docker
Compose stack, or real AWS in cloud deployment).

Backend is selected by `CPG_PULSE_STORAGE_BACKEND` (`local` | `s3`), default
`local`. This is the concrete implementation of the "local-first,
cloud-compatible" principle from docs/architecture.md section 7.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class LakeStorage:
    """Minimal read/write/list interface over the data lake, backend-agnostic."""

    def __init__(self, backend: str | None = None, local_root: str = "data/lake"):
        self.backend = backend or os.environ.get("CPG_PULSE_STORAGE_BACKEND", "local")
        self.local_root = Path(local_root)
        self._s3_client = None
        if self.backend == "s3":
            import boto3

            self._s3_client = boto3.client(
                "s3",
                endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )

    def _bucket_for_layer(self, layer: str) -> str:
        env_var = f"S3_BUCKET_{layer.upper()}"
        return os.environ.get(env_var, f"cpg-pulse-{layer}")

    def put_file(self, layer: str, key: str, local_source_path: str) -> str:
        """Copy a local file into the given lake layer at `key`. Returns the
        location written to (a local path or an s3:// URI) for logging.
        """
        if self.backend == "local":
            dest = self.local_root / layer / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_source_path, dest)
            return str(dest)
        else:
            bucket = self._bucket_for_layer(layer)
            self._s3_client.upload_file(local_source_path, bucket, key)
            return f"s3://{bucket}/{key}"

    def put_bytes(self, layer: str, key: str, data: bytes) -> str:
        if self.backend == "local":
            dest = self.local_root / layer / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return str(dest)
        else:
            bucket = self._bucket_for_layer(layer)
            self._s3_client.put_object(Bucket=bucket, Key=key, Body=data)
            return f"s3://{bucket}/{key}"

    def exists(self, layer: str, key: str) -> bool:
        if self.backend == "local":
            return (self.local_root / layer / key).exists()
        else:
            from botocore.exceptions import ClientError

            try:
                self._s3_client.head_object(Bucket=self._bucket_for_layer(layer), Key=key)
                return True
            except ClientError:
                return False

    def layer_root(self, layer: str) -> str:
        """Return a root path/URI for a layer, suitable for Spark's reader/writer
        (e.g. `spark.read.parquet(storage.layer_root("standardized") + "/pos_sales")`).
        """
        if self.backend == "local":
            return str(self.local_root / layer)
        return f"s3a://{self._bucket_for_layer(layer)}"
