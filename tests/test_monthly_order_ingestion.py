from __future__ import annotations

from datetime import date, datetime, timezone

from monthly_order_ingestion.drive_discovery import DriveFile, select_target_files
from monthly_order_ingestion.manifest import IngestionDecision, ManifestRecord, decide_ingestion
from monthly_order_ingestion.normalization import normalize_headers, normalize_rows, row_hash
from monthly_order_ingestion.sheet_selection import SheetInfo, select_required_sheets
from monthly_order_ingestion.staging_payload import staging_record
from monthly_order_ingestion.bigquery_execution import (
    build_bigquery_execution_plan,
    manifest_success_zero_rows_sql,
    primary_key_validation_sql,
)
from monthly_order_ingestion.config import SOURCES, SheetKind
from monthly_order_ingestion.drive_discovery import TargetFile


def test_select_target_files_requires_exact_name_and_google_sheet() -> None:
    files = [
        DriveFile("1", "monthly_order_202606", "application/vnd.google-apps.spreadsheet", datetime.now(timezone.utc)),
        DriveFile("2", "monthly_order_202606_作業用", "application/vnd.google-apps.spreadsheet", datetime.now(timezone.utc)),
        DriveFile("3", "monthly_order_202606", "text/csv", datetime.now(timezone.utc)),
    ]

    targets = select_target_files("pta", files)

    assert [target.source_file_id for target in targets] == ["1"]
    assert targets[0].source_yyyymm == "202606"


def test_decide_ingestion_uses_successful_manifest_modified_time() -> None:
    target = select_target_files(
        "pta",
        [
            DriveFile(
                "1",
                "monthly_order_202606",
                "application/vnd.google-apps.spreadsheet",
                datetime(2026, 6, 2, tzinfo=timezone.utc),
            )
        ],
    )[0]

    assert decide_ingestion(target, None) == IngestionDecision.INITIAL
    assert (
        decide_ingestion(
            target,
            ManifestRecord("1", "order", datetime(2026, 6, 1, tzinfo=timezone.utc), "success"),
        )
        == IngestionDecision.MODIFIED
    )
    assert (
        decide_ingestion(
            target,
            ManifestRecord("1", "order", datetime(2026, 6, 2, tzinfo=timezone.utc), "success"),
        )
        == IngestionDecision.SKIP
    )
    assert (
        decide_ingestion(
            target,
            ManifestRecord("1", "order", datetime(2026, 6, 2, tzinfo=timezone.utc), "error"),
        )
        == IngestionDecision.MODIFIED
    )


def test_required_sheet_selection() -> None:
    selection = select_required_sheets(
        [
            SheetInfo("注文"),
            SheetInfo("出荷"),
            SheetInfo("キャンセル"),
            SheetInfo("期限切れ"),
            SheetInfo("メモ"),
        ]
    )

    assert len(selection.found) == 4
    assert selection.missing == []


def test_normalize_headers_known_and_duplicate_names() -> None:
    assert normalize_headers(["Order Name", "Lineitem ID", "Lineitem ID", "Discount Codes (Code)"]) == [
        "order_name",
        "lineitem_id",
        "lineitem_id_2",
        "discount_codes_code",
    ]


def test_normalize_rows_adds_common_columns_and_stable_hash() -> None:
    values = [
        ["Order Name", "Lineitem ID", "Lineitem SKU"],
        ["pTa-1", "100", "SKU-1"],
    ]

    rows = normalize_rows(
        values,
        source="pta",
        sheet_kind="order",
        source_file_id="file-1",
        source_file_name="monthly_order_202606",
        source_yyyymm="202606",
        drive_modified_time="2026-06-02T00:00:00Z",
    )

    assert rows[0]["order_name"] == "pTa-1"
    assert rows[0]["source_row_number"] == 2
    assert rows[0]["row_hash"] == row_hash({key: value for key, value in rows[0].items() if key != "row_hash"})


def test_normalize_rows_serializes_dates_from_xlsx() -> None:
    rows = normalize_rows(
        [
            ["Created At", "Updated At", "Lineitem ID", "Lineitem Tax Lines Rates"],
            [datetime(2026, 6, 1, 18, 2, 20), date(2026, 6, 2), 16729635193057.0, 0.1],
        ],
        source="pta",
        sheet_kind="order",
        source_file_id="file-1",
        source_file_name="monthly_order_202606",
        source_yyyymm="202606",
        drive_modified_time="2026-06-02T00:00:00Z",
    )

    assert rows[0]["created_at"] == "2026-06-01 18:02:20"
    assert rows[0]["updated_at"] == "2026-06-02"
    assert rows[0]["lineitem_id"] == "16729635193057"
    assert rows[0]["lineitem_tax_lines_rates"] == "0.1"


def test_staging_record_splits_raw_payload_and_common_columns() -> None:
    row = normalize_rows(
        [["Order Name", "Lineitem ID"], ["pTa-1", "100"]],
        source="pta",
        sheet_kind="order",
        source_file_id="file-1",
        source_file_name="monthly_order_202606",
        source_yyyymm="202606",
        drive_modified_time="2026-06-02T00:00:00Z",
    )[0]

    record = staging_record(row, ingested_at="2026-06-26T00:00:00Z")

    assert record["raw_payload"] == {"order_name": "pTa-1", "lineitem_id": "100"}
    assert record["source"] == "pta"
    assert record["ingested_at"] == "2026-06-26T00:00:00Z"


def test_primary_key_validation_sql_uses_sheet_kind_key_candidates() -> None:
    cancel_sql = primary_key_validation_sql(SOURCES["pta"].tables[SheetKind.CANCEL], SheetKind.CANCEL)
    expired_sql = primary_key_validation_sql(SOURCES["fabli"].tables[SheetKind.EXPIRED], SheetKind.EXPIRED)

    assert "$.cancelled_at" in cancel_sql
    assert "$.updated_at" in expired_sql


def test_bigquery_execution_plan_includes_success_and_error_manifest_sql() -> None:
    plan = build_bigquery_execution_plan(
        SheetKind.ORDER,
        SOURCES["pta"].tables[SheetKind.ORDER],
        load_source_uri_or_path="/tmp/source.jsonl",
    )

    assert "TRUNCATE TABLE" in plan.truncate_staging_sql
    assert "staging_row_count" in plan.row_count_validation_sql
    assert "status = 'success'" in plan.manifest_success_sql
    assert "status = 'error'" in plan.manifest_error_sql_template


def test_cancel_fallback_key_uses_updated_at_and_source_row_number() -> None:
    plan = build_bigquery_execution_plan(
        SheetKind.CANCEL,
        SOURCES["pta"].tables[SheetKind.CANCEL],
        load_source_uri_or_path="/tmp/source.jsonl",
        use_fallback_key=True,
    )

    assert "$.updated_at" in plan.primary_key_validation_sql
    assert "CAST(source_row_number AS STRING)" in plan.primary_key_validation_sql
    assert "CAST(target.source_row_number AS STRING)" in plan.merge_sql


def test_manifest_success_zero_rows_sql_uses_literal_target_metadata() -> None:
    target = TargetFile(
        source="fabli",
        source_file_id="file-1",
        source_file_name="monthly_order_202606",
        source_yyyymm="202606",
        drive_modified_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    sql = manifest_success_zero_rows_sql(SOURCES["fabli"].tables[SheetKind.CANCEL], target, SheetKind.CANCEL)

    assert "monthly_cancel_fabli_ingestion_manifest" in sql
    assert "'fabli' AS source" in sql
    assert "'cancel' AS sheet_kind" in sql
    assert "0 AS row_count" in sql
    assert "status = 'success'" in sql
