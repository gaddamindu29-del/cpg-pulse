"""Shared SparkSession factory.

Local dev runs Spark in local mode against the filesystem paths under
`data/lake/` (see spark/utilities/paths.py) -- no cluster, no S3A connector
jars to configure, so `python spark/jobs/standardize_pos_sales.py` just
works after `pip install -r requirements.txt`. In cloud deployment the same
job code points at S3 via AWS Glue's managed Spark runtime, which supplies
the S3 connector itself -- this module only needs to change
`spark.master`/config, not the job logic. See docs/architecture.md section 7.
"""

from __future__ import annotations

from pyspark.sql import SparkSession


def get_spark_session(app_name: str) -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "8")  # local-mode default (200) is wasteful at this data volume
        .getOrCreate()
    )
