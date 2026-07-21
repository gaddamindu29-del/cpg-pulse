"""Schema drift detection.

Each source's last-known column set is cached as a small JSON file under
`data/_schema_state/<source_name>.json`. Every ingestion run compares the
incoming file's columns against that cache:

- A column present in the cache but missing from `required_columns` that
  disappears, or any wholly new column appearing, is a **compatible** change
  (logged, ingestion proceeds).
- A column listed in `required_columns` disappearing, or a column's inferred
  dtype changing, is a **breaking** change (logged, and the caller decides
  whether to halt -- see base_ingest.run_ingestion).

This directly implements docs/architecture.md section 11 ("Schema
evolution"), and is what makes the generator's deliberate rename
(`reserved_units` -> `reserved_qty` pre-schema-change-date, see
scripts/data_gen/quality_issues.py) a detectable, loggable event rather than a
silent failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATE_DIR = Path("data/_schema_state")


@dataclass
class SchemaChange:
    change_type: str  # COLUMN_ADDED | COLUMN_REMOVED | TYPE_CHANGED
    column_name: str
    is_breaking: bool
    old_value: str | None
    new_value: str | None


def _state_path(source_name: str) -> Path:
    return STATE_DIR / f"{source_name}.json"


def load_last_known_schema(source_name: str) -> dict[str, str] | None:
    path = _state_path(source_name)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_schema(source_name: str, columns_with_dtypes: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(source_name).write_text(json.dumps(columns_with_dtypes, indent=2, sort_keys=True))


def detect_schema_changes(
    source_name: str,
    current_columns_with_dtypes: dict[str, str],
    required_columns: list[str],
) -> list[SchemaChange]:
    """Compare current schema to the cached last-known schema. Returns an
    empty list (and simply caches the schema) on the very first run for a
    source, since there is nothing to compare against yet.
    """
    previous = load_last_known_schema(source_name)
    if previous is None:
        save_schema(source_name, current_columns_with_dtypes)
        return []

    changes: list[SchemaChange] = []
    prev_cols = set(previous.keys())
    curr_cols = set(current_columns_with_dtypes.keys())

    for added in sorted(curr_cols - prev_cols):
        changes.append(SchemaChange("COLUMN_ADDED", added, is_breaking=False, old_value=None, new_value=current_columns_with_dtypes[added]))

    for removed in sorted(prev_cols - curr_cols):
        is_breaking = removed in required_columns
        changes.append(SchemaChange("COLUMN_REMOVED", removed, is_breaking=is_breaking, old_value=previous[removed], new_value=None))

    for common in sorted(prev_cols & curr_cols):
        if previous[common] != current_columns_with_dtypes[common]:
            changes.append(
                SchemaChange("TYPE_CHANGED", common, is_breaking=True, old_value=previous[common], new_value=current_columns_with_dtypes[common])
            )

    save_schema(source_name, current_columns_with_dtypes)
    return changes
