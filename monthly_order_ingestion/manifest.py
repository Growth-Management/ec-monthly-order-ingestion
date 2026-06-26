from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from monthly_order_ingestion.drive_discovery import TargetFile


class IngestionDecision(StrEnum):
    INITIAL = "initial"
    MODIFIED = "modified"
    SKIP = "skip"


@dataclass(frozen=True)
class ManifestRecord:
    source_file_id: str
    sheet_kind: str
    drive_modified_time: datetime | None
    status: str | None
    last_ingested_at: datetime | None = None
    row_count: int | None = None
    error_message: str | None = None


def decide_ingestion(
    target: TargetFile,
    existing: ManifestRecord | None,
) -> IngestionDecision:
    if existing is None:
        return IngestionDecision.INITIAL
    if existing.status != "success":
        return IngestionDecision.MODIFIED
    if existing.drive_modified_time is None:
        return IngestionDecision.MODIFIED
    if target.drive_modified_time > existing.drive_modified_time:
        return IngestionDecision.MODIFIED
    return IngestionDecision.SKIP

