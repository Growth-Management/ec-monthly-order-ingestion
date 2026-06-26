from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
MONTHLY_ORDER_RE = re.compile(r"^monthly_order_(\d{6})$")


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: datetime
    url: str | None = None
    md5_checksum: str | None = None
    sha1_checksum: str | None = None
    sha256_checksum: str | None = None


@dataclass(frozen=True)
class TargetFile:
    source: str
    source_file_id: str
    source_file_name: str
    source_yyyymm: str
    drive_modified_time: datetime
    url: str | None = None
    md5_checksum: str | None = None
    sha1_checksum: str | None = None
    sha256_checksum: str | None = None


def parse_drive_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def match_source_yyyymm(name: str) -> str | None:
    matched = MONTHLY_ORDER_RE.fullmatch(name)
    if not matched:
        return None
    return matched.group(1)


def select_target_files(source: str, files: Iterable[DriveFile]) -> list[TargetFile]:
    targets: list[TargetFile] = []
    for file in files:
        source_yyyymm = match_source_yyyymm(file.name)
        if source_yyyymm is None:
            continue
        if file.mime_type != GOOGLE_SHEETS_MIME_TYPE:
            continue
        targets.append(
            TargetFile(
                source=source,
                source_file_id=file.id,
                source_file_name=file.name,
                source_yyyymm=source_yyyymm,
                drive_modified_time=file.modified_time,
                url=file.url,
                md5_checksum=file.md5_checksum,
                sha1_checksum=file.sha1_checksum,
                sha256_checksum=file.sha256_checksum,
            )
        )
    return sorted(targets, key=lambda item: (item.source_yyyymm, item.source_file_id))

