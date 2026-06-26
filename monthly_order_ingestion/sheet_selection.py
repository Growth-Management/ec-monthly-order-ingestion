from __future__ import annotations

from dataclasses import dataclass

from monthly_order_ingestion.config import SHEET_TITLES, SheetKind


@dataclass(frozen=True)
class SheetInfo:
    title: str
    sheet_id: int | None = None
    row_count: int | None = None
    column_count: int | None = None


@dataclass(frozen=True)
class SheetSelection:
    found: dict[SheetKind, SheetInfo]
    missing: list[SheetKind]


def select_required_sheets(sheets: list[SheetInfo]) -> SheetSelection:
    by_title = {sheet.title: sheet for sheet in sheets}
    found: dict[SheetKind, SheetInfo] = {}
    missing: list[SheetKind] = []
    for kind, title in SHEET_TITLES.items():
        if title in by_title:
            found[kind] = by_title[title]
        else:
            missing.append(kind)
    return SheetSelection(found=found, missing=missing)

