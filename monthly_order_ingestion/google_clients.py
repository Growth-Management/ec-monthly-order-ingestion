from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import bigquery

from monthly_order_ingestion.drive_discovery import DriveFile, parse_drive_time
from monthly_order_ingestion.manifest import ManifestRecord
from monthly_order_ingestion.sheet_selection import SheetInfo


@dataclass(frozen=True)
class GoogleClients:
    drive: object
    sheets: object
    bigquery: object


GOOGLE_API_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/bigquery",
)

DRIVE_SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)

BIGQUERY_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)

AUTHORIZED_USER_JSON_ENV = "GOOGLE_AUTHORIZED_USER_JSON"
AUTHORIZED_USER_FILE_ENV = "GOOGLE_AUTHORIZED_USER_FILE"


def is_retryable_api_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionResetError, TimeoutError)):
        return True
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status in {429, 500, 502, 503, 504}


def execute_with_retry(operation, *, max_attempts: int = 5, base_sleep_seconds: float = 1.0):
    attempt = 1
    while True:
        try:
            return operation()
        except Exception as exc:
            if attempt >= max_attempts or not is_retryable_api_error(exc):
                raise
            time.sleep(base_sleep_seconds * (2 ** (attempt - 1)))
            attempt += 1


def authorized_user_info_from_env() -> dict | None:
    if token_json := os.getenv(AUTHORIZED_USER_JSON_ENV):
        return json.loads(token_json)
    if token_file := os.getenv(AUTHORIZED_USER_FILE_ENV):
        with open(token_file, encoding="utf-8") as file_obj:
            return json.load(file_obj)
    return None


def drive_sheets_credentials():
    import google.auth
    from google.oauth2.credentials import Credentials

    if authorized_user_info := authorized_user_info_from_env():
        return Credentials.from_authorized_user_info(authorized_user_info, scopes=DRIVE_SHEETS_SCOPES)
    credentials, _ = google.auth.default(scopes=GOOGLE_API_SCOPES)
    return credentials


def bigquery_credentials():
    import google.auth

    credentials, _ = google.auth.default(scopes=BIGQUERY_SCOPES)
    return credentials


def build_google_clients(project_id: str) -> GoogleClients:
    from google.cloud import bigquery
    from googleapiclient.discovery import build

    drive_credentials = drive_sheets_credentials()
    bq_credentials = bigquery_credentials()
    return GoogleClients(
        drive=build("drive", "v3", credentials=drive_credentials),
        sheets=build("sheets", "v4", credentials=drive_credentials),
        bigquery=bigquery.Client(project=project_id, credentials=bq_credentials),
    )


def list_drive_folder_files(drive_service: object, folder_id: str) -> list[DriveFile]:
    files: list[DriveFile] = []
    page_token = None
    fields = (
        "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,"
        "md5Checksum,sha1Checksum,sha256Checksum)"
    )
    while True:
        response = (
            execute_with_retry(lambda: drive_service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=fields,
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute())
        )
        for item in response.get("files", []):
            files.append(
                DriveFile(
                    id=item["id"],
                    name=item["name"],
                    mime_type=item["mimeType"],
                    modified_time=parse_drive_time(item["modifiedTime"]),
                    url=item.get("webViewLink"),
                    md5_checksum=item.get("md5Checksum"),
                    sha1_checksum=item.get("sha1Checksum"),
                    sha256_checksum=item.get("sha256Checksum"),
                )
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def list_spreadsheet_sheets(sheets_service: object, spreadsheet_id: str) -> list[SheetInfo]:
    response = (
        execute_with_retry(lambda: sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title,gridProperties))")
        .execute())
    )
    sheets: list[SheetInfo] = []
    for sheet in response.get("sheets", []):
        properties = sheet["properties"]
        grid = properties.get("gridProperties", {})
        sheets.append(
            SheetInfo(
                title=properties["title"],
                sheet_id=properties.get("sheetId"),
                row_count=grid.get("rowCount"),
                column_count=grid.get("columnCount"),
            )
        )
    return sheets


def read_sheet_values(sheets_service: object, spreadsheet_id: str, sheet_title: str) -> list[list[str]]:
    response = (
        execute_with_retry(lambda: sheets_service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_title}'",
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute())
    )
    return response.get("values", [])


def fetch_manifest_records(
    client: "bigquery.Client",
    manifest_table: str,
    source_file_ids: Iterable[str],
    sheet_kind: str,
) -> dict[str, ManifestRecord]:
    from google.cloud import bigquery

    ids = list(source_file_ids)
    if not ids:
        return {}
    sql = f"""
    SELECT source_file_id, sheet_kind, drive_modified_time, status, last_ingested_at, row_count, error_message
    FROM `{manifest_table}`
    WHERE source_file_id IN UNNEST(@source_file_ids)
      AND sheet_kind = @sheet_kind
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY source_file_id, sheet_kind
      ORDER BY updated_manifest_at DESC
    ) = 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("source_file_ids", "STRING", ids),
            bigquery.ScalarQueryParameter("sheet_kind", "STRING", sheet_kind),
        ]
    )
    records: dict[str, ManifestRecord] = {}
    for row in client.query(sql, job_config=job_config).result():
        records[row.source_file_id] = ManifestRecord(
            source_file_id=row.source_file_id,
            sheet_kind=row.sheet_kind,
            drive_modified_time=row.drive_modified_time,
            status=row.status,
            last_ingested_at=row.last_ingested_at,
            row_count=row.row_count,
            error_message=row.error_message,
        )
    return records
