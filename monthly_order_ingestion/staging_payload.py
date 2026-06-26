from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from monthly_order_ingestion.normalization import INGESTION_COLUMNS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def raw_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in INGESTION_COLUMNS and key not in {"ingested_at", "updated_ingestion_at"}
    }


def staging_record(row: dict[str, Any], *, ingested_at: str | None = None) -> dict[str, Any]:
    timestamp = ingested_at or utc_now_iso()
    return {
        "raw_payload": raw_payload_from_row(row),
        "source": row["source"],
        "sheet_kind": row["sheet_kind"],
        "source_file_id": row["source_file_id"],
        "source_file_name": row["source_file_name"],
        "source_yyyymm": row["source_yyyymm"],
        "source_row_number": row["source_row_number"],
        "drive_modified_time": row["drive_modified_time"],
        "row_hash": row["row_hash"],
        "ingested_at": timestamp,
        "updated_ingestion_at": None,
    }


def write_staging_jsonl(
    rows: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    ingested_at: str | None = None,
) -> int:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(staging_record(row, ingested_at=ingested_at), ensure_ascii=False, sort_keys=True))
            output.write("\n")
            count += 1
    return count

