from __future__ import annotations

from dataclasses import dataclass

from monthly_order_ingestion.config import SheetKind, SourceConfig
from monthly_order_ingestion.drive_discovery import TargetFile, select_target_files
from monthly_order_ingestion.manifest import IngestionDecision, ManifestRecord, decide_ingestion
from monthly_order_ingestion.sheet_selection import SheetInfo, SheetSelection, select_required_sheets


@dataclass(frozen=True)
class FilePlan:
    target: TargetFile
    sheet_selection: SheetSelection
    decisions: dict[SheetKind, IngestionDecision]


def build_file_targets(source_config: SourceConfig, drive_files) -> list[TargetFile]:
    return select_target_files(source_config.source, drive_files)


def build_file_plan(
    target: TargetFile,
    sheets: list[SheetInfo],
    manifest_by_sheet: dict[SheetKind, ManifestRecord | None],
) -> FilePlan:
    selection = select_required_sheets(sheets)
    decisions = {
        kind: decide_ingestion(target, manifest_by_sheet.get(kind))
        for kind in selection.found
    }
    return FilePlan(target=target, sheet_selection=selection, decisions=decisions)

