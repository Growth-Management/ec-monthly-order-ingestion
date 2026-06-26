from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


PROJECT_ID = "ice-ec-project"
DATASET_ID = "ice_ec_source"


class SheetKind(StrEnum):
    ORDER = "order"
    SHIPPING = "shipping"
    CANCEL = "cancel"
    EXPIRED = "expired"


SHEET_TITLES: dict[SheetKind, str] = {
    SheetKind.ORDER: "注文",
    SheetKind.SHIPPING: "出荷",
    SheetKind.CANCEL: "キャンセル",
    SheetKind.EXPIRED: "期限切れ",
}


@dataclass(frozen=True)
class SheetTables:
    main: str
    staging: str
    manifest: str


@dataclass(frozen=True)
class SourceConfig:
    source: str
    folder_id: str
    tables: dict[SheetKind, SheetTables]


def table_ref(table_id: str) -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.{table_id}"


def source_config(source: str, folder_id: str) -> SourceConfig:
    return SourceConfig(
        source=source,
        folder_id=folder_id,
        tables={
            kind: SheetTables(
                main=table_ref(f"monthly_{kind.value}_{source}"),
                staging=table_ref(f"monthly_{kind.value}_{source}_staging"),
                manifest=table_ref(f"monthly_{kind.value}_{source}_ingestion_manifest"),
            )
            for kind in SheetKind
        },
    )


SOURCES: dict[str, SourceConfig] = {
    "pta": source_config("pta", "1GJ8Z3gKTb9h8nG6n01amNbM4Ortkxe64"),
    "fabli": source_config("fabli", "1GfVxojNBBLKd-E0q1c58ysaxc00lGQ8j"),
}

