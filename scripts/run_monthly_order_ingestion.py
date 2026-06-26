from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monthly_order_ingestion.bigquery_execution import (
    build_bigquery_execution_plan,
    load_jsonl_to_staging,
    manifest_success_zero_rows_sql,
)
from monthly_order_ingestion.config import PROJECT_ID, SHEET_TITLES, SOURCES, SheetKind
from monthly_order_ingestion.google_clients import (
    build_google_clients,
    fetch_manifest_records,
    list_drive_folder_files,
    list_spreadsheet_sheets,
)
from monthly_order_ingestion.manifest import IngestionDecision
from monthly_order_ingestion.normalization import normalize_rows
from monthly_order_ingestion.pipeline import build_file_plan, build_file_targets
from monthly_order_ingestion.staging_payload import write_staging_jsonl
from scripts.xlsx_sheet_to_jsonl import worksheet_values


XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def cancel_uses_fallback_key(kind: SheetKind) -> bool:
    return kind == SheetKind.CANCEL


def export_spreadsheet_xlsx(drive_service: Any, spreadsheet_id: str, output_path: Path) -> None:
    request = drive_service.files().export_media(fileId=spreadsheet_id, mimeType=XLSX_MIME_TYPE)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as file_obj:
        downloader = MediaIoBaseDownload(file_obj, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()


def normalize_sheet_to_jsonl(
    xlsx_path: Path,
    target,
    kind: SheetKind,
    output_path: Path,
) -> int:
    values = worksheet_values(xlsx_path, SHEET_TITLES[kind])
    rows = normalize_rows(
        values,
        source=target.source,
        sheet_kind=kind.value,
        source_file_id=target.source_file_id,
        source_file_name=target.source_file_name,
        source_yyyymm=target.source_yyyymm,
        drive_modified_time=target.drive_modified_time.isoformat().replace("+00:00", "Z"),
    )
    return write_staging_jsonl(rows, output_path)


def run_query(client: bigquery.Client, sql: str) -> None:
    client.query(sql).result()


def run_parameterized_error_manifest(
    client: bigquery.Client,
    sql: str,
    *,
    target,
    kind: SheetKind,
    error_message: str,
) -> None:
    job_config = QueryJobConfig(
        query_parameters=[
            ScalarQueryParameter("source", "STRING", target.source),
            ScalarQueryParameter("sheet_kind", "STRING", kind.value),
            ScalarQueryParameter("source_file_id", "STRING", target.source_file_id),
            ScalarQueryParameter("source_file_name", "STRING", target.source_file_name),
            ScalarQueryParameter("source_yyyymm", "STRING", target.source_yyyymm),
            ScalarQueryParameter("drive_modified_time", "TIMESTAMP", target.drive_modified_time),
            ScalarQueryParameter("error_message", "STRING", error_message[:8000]),
        ]
    )
    client.query(sql, job_config=job_config).result()


def validate_primary_key(client: bigquery.Client, validation_sql: str) -> list[bigquery.table.Row]:
    return list(client.query(validation_sql).result())


def fetch_manifest_records_for_source(client: bigquery.Client, source_config, targets):
    target_ids = [target.source_file_id for target in targets]
    manifest_by_kind = {}
    for kind, tables in source_config.tables.items():
        manifest_by_kind[kind] = fetch_manifest_records(client, tables.manifest, target_ids, kind.value)
    return manifest_by_kind


def process_sheet(
    clients,
    *,
    target,
    kind: SheetKind,
    xlsx_path: Path,
    output_dir: Path,
    dry_run: bool,
) -> str:
    tables = SOURCES[target.source].tables[kind]
    jsonl_path = output_dir / f"{target.source}_{target.source_yyyymm}_{kind.value}.jsonl"
    row_count = normalize_sheet_to_jsonl(xlsx_path, target, kind, jsonl_path)
    plan = build_bigquery_execution_plan(
        kind,
        tables,
        load_source_uri_or_path=str(jsonl_path),
        use_fallback_key=cancel_uses_fallback_key(kind),
    )

    if dry_run:
        return f"DRY {target.source} {target.source_yyyymm} {kind.value}: {row_count} rows -> {jsonl_path}"

    run_query(clients.bigquery, plan.truncate_staging_sql)
    if row_count > 0:
        load_jsonl_to_staging(clients.bigquery, tables, jsonl_path).result()
        key_issues = validate_primary_key(clients.bigquery, plan.primary_key_validation_sql)
        if key_issues:
            raise RuntimeError(f"primary key validation failed: {len(key_issues)} issue rows")
        run_query(clients.bigquery, plan.merge_sql)
        run_query(clients.bigquery, plan.manifest_success_sql)
    else:
        run_query(clients.bigquery, manifest_success_zero_rows_sql(tables, target, kind))
    return f"OK {target.source} {target.source_yyyymm} {kind.value}: {row_count} rows"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run monthly_order Drive to BigQuery ingestion.")
    parser.add_argument("--source", choices=sorted(SOURCES), help="Optional source.")
    parser.add_argument("--from-yyyymm", help="Inclusive lower bound, e.g. 202501.")
    parser.add_argument("--to-yyyymm", help="Inclusive upper bound, e.g. 202606.")
    parser.add_argument(
        "--mode",
        choices=["delta", "full"],
        default="delta",
        help="delta respects manifest modifiedTime; full processes all target files in range.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover and generate JSONL only; do not write BigQuery.")
    parser.add_argument("--work-dir", default="/tmp/monthly_order_ingestion")
    args = parser.parse_args()

    clients = build_google_clients(PROJECT_ID)
    source_items = [(args.source, SOURCES[args.source])] if args.source else SOURCES.items()
    work_dir = Path(args.work_dir)
    output_dir = work_dir / "jsonl"
    xlsx_dir = work_dir / "xlsx"
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_dir.mkdir(parents=True, exist_ok=True)

    for source_name, source_config in source_items:
        drive_files = list_drive_folder_files(clients.drive, source_config.folder_id)
        targets = build_file_targets(source_config, drive_files)
        if args.from_yyyymm:
            targets = [target for target in targets if target.source_yyyymm >= args.from_yyyymm]
        if args.to_yyyymm:
            targets = [target for target in targets if target.source_yyyymm <= args.to_yyyymm]

        manifest_by_kind = fetch_manifest_records_for_source(clients.bigquery, source_config, targets)
        print(f"# {source_name}: {len(targets)} exact-match target files")

        for target in targets:
            sheets = list_spreadsheet_sheets(clients.sheets, target.source_file_id)
            plan = build_file_plan(
                target,
                sheets,
                {kind: manifest_by_kind.get(kind, {}).get(target.source_file_id) for kind in SheetKind},
            )
            kinds_to_process: list[SheetKind] = []
            for kind in SheetKind:
                if kind not in plan.sheet_selection.found:
                    print(f"MISS {target.source} {target.source_yyyymm} {kind.value}: sheet missing")
                    continue
                if args.mode == "full" or plan.decisions.get(kind) != IngestionDecision.SKIP:
                    kinds_to_process.append(kind)

            if not kinds_to_process:
                print(f"SKIP {target.source} {target.source_yyyymm}: manifest up to date")
                continue

            xlsx_path = xlsx_dir / f"{target.source}_{target.source_yyyymm}_{target.source_file_id}.xlsx"
            export_spreadsheet_xlsx(clients.drive, target.source_file_id, xlsx_path)
            for kind in kinds_to_process:
                try:
                    print(process_sheet(clients, target=target, kind=kind, xlsx_path=xlsx_path, output_dir=output_dir, dry_run=args.dry_run))
                except Exception as exc:  # noqa: BLE001
                    tables = source_config.tables[kind]
                    print(f"ERROR {target.source} {target.source_yyyymm} {kind.value}: {exc}", file=sys.stderr)
                    if not args.dry_run:
                        run_parameterized_error_manifest(
                            clients.bigquery,
                            build_bigquery_execution_plan(kind, tables, load_source_uri_or_path="").manifest_error_sql_template,
                            target=target,
                            kind=kind,
                            error_message=str(exc),
                        )


if __name__ == "__main__":
    main()
