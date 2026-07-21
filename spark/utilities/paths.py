"""Lake layer path resolution for Spark jobs -- mirrors
ingestion/common/storage.py's local-vs-s3 backend selection so ingestion and
standardization agree on where the raw layer actually is.
"""

from __future__ import annotations

import os


def layer_path(layer: str, *parts: str) -> str:
    backend = os.environ.get("CPG_PULSE_STORAGE_BACKEND", "local")
    if backend == "local":
        base = os.path.join("data", "lake", layer, *parts)
        return base
    bucket = os.environ.get(f"S3_BUCKET_{layer.upper()}", f"cpg-pulse-{layer}")
    suffix = "/".join(parts)
    return f"s3a://{bucket}/{suffix}" if suffix else f"s3a://{bucket}"
