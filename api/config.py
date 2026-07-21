"""API configuration, read entirely from environment variables (.env in local
dev, container env vars in Docker/cloud) -- never hardcoded, per
docs/architecture.md section 13 ("Security Considerations").
"""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.warehouse_db_host = os.environ.get("WAREHOUSE_DB_HOST", "localhost")
        self.warehouse_db_port = os.environ.get("WAREHOUSE_DB_PORT", "5432")
        self.warehouse_db_name = os.environ.get("WAREHOUSE_DB_NAME", "cpg_pulse_warehouse")
        self.warehouse_db_user = os.environ.get("WAREHOUSE_DB_USER", "cpgpulse")
        self.warehouse_db_password = os.environ.get("WAREHOUSE_DB_PASSWORD", "")

        self.metadata_db_host = os.environ.get("METADATA_DB_HOST", "localhost")
        self.metadata_db_port = os.environ.get("METADATA_DB_PORT", "5432")
        self.metadata_db_name = os.environ.get("METADATA_DB_NAME", "cpg_pulse_metadata")
        self.metadata_db_user = os.environ.get("METADATA_DB_USER", "cpgpulse")
        self.metadata_db_password = os.environ.get("METADATA_DB_PASSWORD", "")

        self.api_host = os.environ.get("API_HOST", "0.0.0.0")
        self.api_port = int(os.environ.get("API_PORT", "8000"))

    @property
    def warehouse_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.warehouse_db_user}:{self.warehouse_db_password}"
            f"@{self.warehouse_db_host}:{self.warehouse_db_port}/{self.warehouse_db_name}"
        )

    @property
    def metadata_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.metadata_db_user}:{self.metadata_db_password}"
            f"@{self.metadata_db_host}:{self.metadata_db_port}/{self.metadata_db_name}"
        )


settings = Settings()
