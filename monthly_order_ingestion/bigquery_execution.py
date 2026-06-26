from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.cloud import bigquery

from monthly_order_ingestion.config import SheetKind, SheetTables
from monthly_order_ingestion.drive_discovery import TargetFile
from monthly_order_ingestion.sql import merge_sql


@dataclass(frozen=True)
class BigQueryExecutionPlan:
    truncate_staging_sql: str
    load_source_uri_or_path: str
    row_count_validation_sql: str
    merge_sql: str
    manifest_success_sql: str
    manifest_error_sql_template: str
    primary_key_validation_sql: str


def truncate_staging_sql(tables: SheetTables) -> str:
    return f"TRUNCATE TABLE `{tables.staging}`;"


def load_jsonl_to_staging(client: Any, tables: SheetTables, jsonl_path: str | Path) -> Any:
    from google.cloud import bigquery

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[
            bigquery.SchemaField("raw_payload", "JSON"),
            bigquery.SchemaField("source", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("sheet_kind", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("source_file_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("source_file_name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("source_yyyymm", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("source_row_number", "INTEGER", mode="REQUIRED"),
            bigquery.SchemaField("drive_modified_time", "TIMESTAMP"),
            bigquery.SchemaField("row_hash", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("updated_ingestion_at", "TIMESTAMP"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    with Path(jsonl_path).open("rb") as source_file:
        return client.load_table_from_file(source_file, tables.staging, job_config=job_config)


def primary_key_expression(kind: SheetKind, *, use_fallback_key: bool = False) -> list[str]:
    if use_fallback_key:
        if kind == SheetKind.SHIPPING:
            return ["order_name", "lineitem_id", "shipping_lines_ids", "source_row_number"]
        if kind == SheetKind.CANCEL:
            return ["order_name", "lineitem_id", "updated_at", "source_row_number"]
        if kind == SheetKind.EXPIRED:
            return ["order_name", "lineitem_id", "lineitem_sku", "source_row_number"]
        return ["order_name", "lineitem_id", "lineitem_sku", "source_row_number"]
    if kind == SheetKind.CANCEL:
        return ["order_name", "lineitem_id", "cancelled_at"]
    if kind == SheetKind.EXPIRED:
        return ["order_name", "lineitem_id", "updated_at"]
    return ["order_name", "lineitem_id"]


def json_or_column_expression(key: str) -> str:
    if key == "source_row_number":
        return "CAST(source_row_number AS STRING) AS source_row_number"
    return f"JSON_VALUE(raw_payload, '$.{key}') AS {key}"


def source_value_expression(key: str) -> str:
    if key == "source_row_number":
        return "CAST(source.source_row_number AS STRING)"
    if key in {"created_at", "updated_at", "cancelled_at"}:
        return f"SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.{key}'))"
    return f"JSON_VALUE(source.raw_payload, '$.{key}')"


def target_value_expression(key: str) -> str:
    if key == "source_row_number":
        return "CAST(target.source_row_number AS STRING)"
    if key in {"created_at", "updated_at", "cancelled_at"}:
        return f"target.{key}"
    return f"target.{key}"


def primary_key_validation_sql(tables: SheetTables, kind: SheetKind, *, use_fallback_key: bool = False) -> str:
    keys = primary_key_expression(kind, use_fallback_key=use_fallback_key)
    select_keys = ", ".join(keys)
    json_keys = ", ".join([json_or_column_expression(key) for key in keys])
    passthrough_columns = ["source_file_id"]
    if "source_row_number" not in keys:
        passthrough_columns.append("source_row_number")
    passthrough_sql = ", ".join(passthrough_columns)
    null_checks = " OR ".join([f"{key} IS NULL OR {key} = ''" for key in keys])
    join_keys = ", ".join(keys)
    return f"""WITH normalized AS (
  SELECT {json_keys}, {passthrough_sql}
  FROM `{tables.staging}`
),
null_key_rows AS (
  SELECT 'null_key' AS issue_type, {select_keys}, COUNT(*) AS row_count
  FROM normalized
  WHERE {null_checks}
  GROUP BY {select_keys}
),
duplicate_key_rows AS (
  SELECT 'duplicate_key' AS issue_type, {select_keys}, COUNT(*) AS row_count
  FROM normalized
  GROUP BY {select_keys}
  HAVING COUNT(*) > 1
)
SELECT * FROM null_key_rows
UNION ALL
SELECT * FROM duplicate_key_rows
ORDER BY issue_type, row_count DESC, {join_keys};"""


def merge_match_condition(kind: SheetKind, *, use_fallback_key: bool = False) -> str:
    if use_fallback_key:
        keys = primary_key_expression(kind, use_fallback_key=True)
        return "\nAND ".join(
            f"{target_value_expression(key)} = {source_value_expression(key)}"
            for key in keys
        )
    if kind == SheetKind.CANCEL:
        return """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
AND target.cancelled_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.cancelled_at'))
""".strip()
    if kind == SheetKind.EXPIRED:
        return """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
AND target.updated_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.updated_at'))
""".strip()
    return """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
""".strip()


def merge_sql_with_key(kind: SheetKind, tables: SheetTables, *, use_fallback_key: bool = False) -> str:
    if not use_fallback_key:
        return merge_sql(kind, tables)
    base_sql = merge_sql(kind, tables)
    old_condition = merge_match_condition(kind, use_fallback_key=False)
    return base_sql.replace(f"ON {old_condition}", f"ON {merge_match_condition(kind, use_fallback_key=True)}", 1)


def row_count_validation_sql(tables: SheetTables) -> str:
    return f"""SELECT
  source,
  sheet_kind,
  source_file_id,
  source_file_name,
  source_yyyymm,
  COUNT(*) AS staging_row_count,
  MIN(source_row_number) AS min_source_row_number,
  MAX(source_row_number) AS max_source_row_number
FROM `{tables.staging}`
GROUP BY source, sheet_kind, source_file_id, source_file_name, source_yyyymm
ORDER BY source_yyyymm, source_file_name, sheet_kind;"""


def manifest_success_sql(tables: SheetTables) -> str:
    return f"""MERGE `{tables.manifest}` AS target
USING (
  SELECT
    ANY_VALUE(source) AS source,
    ANY_VALUE(sheet_kind) AS sheet_kind,
    source_file_id,
    ANY_VALUE(source_file_name) AS source_file_name,
    ANY_VALUE(source_yyyymm) AS source_yyyymm,
    ANY_VALUE(drive_modified_time) AS drive_modified_time,
    COUNT(*) AS row_count,
    CURRENT_TIMESTAMP() AS manifest_updated_at
  FROM `{tables.staging}`
  GROUP BY source_file_id
) AS source
ON target.source_file_id = source.source_file_id
AND target.sheet_kind = source.sheet_kind
WHEN MATCHED THEN
  UPDATE SET
    source_file_name = source.source_file_name,
    source_yyyymm = source.source_yyyymm,
    drive_modified_time = source.drive_modified_time,
    last_ingested_at = source.manifest_updated_at,
    row_count = source.row_count,
    status = 'success',
    error_message = NULL,
    updated_manifest_at = source.manifest_updated_at
WHEN NOT MATCHED THEN
  INSERT (
    source, sheet_kind, source_file_id, source_file_name, source_yyyymm,
    drive_modified_time, last_ingested_at, row_count, status, error_message,
    created_manifest_at, updated_manifest_at
  )
  VALUES (
    source.source, source.sheet_kind, source.source_file_id, source.source_file_name,
    source.source_yyyymm, source.drive_modified_time, source.manifest_updated_at,
    source.row_count, 'success', NULL, source.manifest_updated_at, source.manifest_updated_at
  );"""


def manifest_success_zero_rows_sql(tables: SheetTables, target: TargetFile, kind: SheetKind) -> str:
    return f"""MERGE `{tables.manifest}` AS target
USING (
  SELECT
    '{target.source}' AS source,
    '{kind.value}' AS sheet_kind,
    '{target.source_file_id}' AS source_file_id,
    '{target.source_file_name}' AS source_file_name,
    '{target.source_yyyymm}' AS source_yyyymm,
    TIMESTAMP('{target.drive_modified_time.isoformat()}') AS drive_modified_time,
    0 AS row_count,
    CURRENT_TIMESTAMP() AS manifest_updated_at
) AS source
ON target.source_file_id = source.source_file_id
AND target.sheet_kind = source.sheet_kind
WHEN MATCHED THEN
  UPDATE SET
    source_file_name = source.source_file_name,
    source_yyyymm = source.source_yyyymm,
    drive_modified_time = source.drive_modified_time,
    last_ingested_at = source.manifest_updated_at,
    row_count = source.row_count,
    status = 'success',
    error_message = NULL,
    updated_manifest_at = source.manifest_updated_at
WHEN NOT MATCHED THEN
  INSERT (
    source, sheet_kind, source_file_id, source_file_name, source_yyyymm,
    drive_modified_time, last_ingested_at, row_count, status, error_message,
    created_manifest_at, updated_manifest_at
  )
  VALUES (
    source.source, source.sheet_kind, source.source_file_id, source.source_file_name,
    source.source_yyyymm, source.drive_modified_time, source.manifest_updated_at,
    source.row_count, 'success', NULL, source.manifest_updated_at, source.manifest_updated_at
  );"""


def manifest_error_sql_template(tables: SheetTables) -> str:
    return f"""MERGE `{tables.manifest}` AS target
USING (
  SELECT
    @source AS source,
    @sheet_kind AS sheet_kind,
    @source_file_id AS source_file_id,
    @source_file_name AS source_file_name,
    @source_yyyymm AS source_yyyymm,
    @drive_modified_time AS drive_modified_time,
    @error_message AS error_message,
    CURRENT_TIMESTAMP() AS manifest_updated_at
) AS source
ON target.source_file_id = source.source_file_id
AND target.sheet_kind = source.sheet_kind
WHEN MATCHED THEN
  UPDATE SET
    source_file_name = source.source_file_name,
    source_yyyymm = source.source_yyyymm,
    drive_modified_time = source.drive_modified_time,
    status = 'error',
    error_message = source.error_message,
    updated_manifest_at = source.manifest_updated_at
WHEN NOT MATCHED THEN
  INSERT (
    source, sheet_kind, source_file_id, source_file_name, source_yyyymm,
    drive_modified_time, last_ingested_at, row_count, status, error_message,
    created_manifest_at, updated_manifest_at
  )
  VALUES (
    source.source, source.sheet_kind, source.source_file_id, source.source_file_name,
    source.source_yyyymm, source.drive_modified_time, NULL, NULL, 'error',
    source.error_message, source.manifest_updated_at, source.manifest_updated_at
  );"""


def build_bigquery_execution_plan(
    kind: SheetKind,
    tables: SheetTables,
    *,
    load_source_uri_or_path: str,
    use_fallback_key: bool = False,
) -> BigQueryExecutionPlan:
    return BigQueryExecutionPlan(
        truncate_staging_sql=truncate_staging_sql(tables),
        load_source_uri_or_path=load_source_uri_or_path,
        row_count_validation_sql=row_count_validation_sql(tables),
        merge_sql=merge_sql_with_key(kind, tables, use_fallback_key=use_fallback_key),
        manifest_success_sql=manifest_success_sql(tables),
        manifest_error_sql_template=manifest_error_sql_template(tables),
        primary_key_validation_sql=primary_key_validation_sql(tables, kind, use_fallback_key=use_fallback_key),
    )
