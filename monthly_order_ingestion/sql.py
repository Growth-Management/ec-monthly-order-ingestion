from __future__ import annotations

from monthly_order_ingestion.config import SheetKind, SheetTables


COMMON_COLUMNS_SQL = """
source STRING NOT NULL,
sheet_kind STRING NOT NULL,
source_file_id STRING NOT NULL,
source_file_name STRING NOT NULL,
source_yyyymm STRING NOT NULL,
source_row_number INT64 NOT NULL,
drive_modified_time TIMESTAMP,
row_hash STRING NOT NULL,
ingested_at TIMESTAMP NOT NULL,
updated_ingestion_at TIMESTAMP
""".strip()


MANIFEST_COLUMNS_SQL = """
source STRING NOT NULL,
sheet_kind STRING NOT NULL,
source_file_id STRING NOT NULL,
source_file_name STRING NOT NULL,
source_yyyymm STRING NOT NULL,
drive_modified_time TIMESTAMP,
last_ingested_at TIMESTAMP,
row_count INT64,
status STRING NOT NULL,
error_message STRING,
md5_checksum STRING,
sha1_checksum STRING,
sha256_checksum STRING,
sheet_title STRING,
sheet_id INT64,
created_manifest_at TIMESTAMP NOT NULL,
updated_manifest_at TIMESTAMP NOT NULL
""".strip()


def create_staging_table_sql(tables: SheetTables) -> str:
    return f"""CREATE TABLE IF NOT EXISTS `{tables.staging}` (
  raw_payload JSON,
  {COMMON_COLUMNS_SQL}
);"""


def create_manifest_table_sql(tables: SheetTables) -> str:
    return f"""CREATE TABLE IF NOT EXISTS `{tables.manifest}` (
  {MANIFEST_COLUMNS_SQL}
)
CLUSTER BY source_yyyymm, source_file_id, sheet_kind;"""


def create_main_table_sql(tables: SheetTables) -> str:
    return f"""CREATE TABLE IF NOT EXISTS `{tables.main}` (
  raw_payload JSON,
  {COMMON_COLUMNS_SQL},
  order_name STRING,
  lineitem_id STRING,
  lineitem_sku STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  cancelled_at TIMESTAMP,
  shipping_lines_ids STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY source_yyyymm, order_name, lineitem_id;"""


def merge_sql(kind: SheetKind, tables: SheetTables) -> str:
    if kind == SheetKind.CANCEL:
        match = """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
AND target.cancelled_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.cancelled_at'))
""".strip()
    elif kind == SheetKind.EXPIRED:
        match = """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
AND target.updated_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.updated_at'))
""".strip()
    else:
        match = """
target.order_name = JSON_VALUE(source.raw_payload, '$.order_name')
AND target.lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id')
""".strip()

    return f"""MERGE `{tables.main}` AS target
USING `{tables.staging}` AS source
ON {match}
WHEN MATCHED AND target.row_hash != source.row_hash THEN
  UPDATE SET
    raw_payload = source.raw_payload,
    source_file_id = source.source_file_id,
    source_file_name = source.source_file_name,
    source_yyyymm = source.source_yyyymm,
    source_row_number = source.source_row_number,
    drive_modified_time = source.drive_modified_time,
    row_hash = source.row_hash,
    updated_ingestion_at = CURRENT_TIMESTAMP(),
    order_name = JSON_VALUE(source.raw_payload, '$.order_name'),
    lineitem_id = JSON_VALUE(source.raw_payload, '$.lineitem_id'),
    lineitem_sku = JSON_VALUE(source.raw_payload, '$.lineitem_sku'),
    created_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.created_at')),
    updated_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.updated_at')),
    cancelled_at = SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.cancelled_at')),
    shipping_lines_ids = JSON_VALUE(source.raw_payload, '$.shipping_lines_ids')
WHEN NOT MATCHED THEN
  INSERT (
    raw_payload, source, sheet_kind, source_file_id, source_file_name, source_yyyymm,
    source_row_number, drive_modified_time, row_hash, ingested_at, updated_ingestion_at,
    order_name, lineitem_id, lineitem_sku, created_at, updated_at, cancelled_at, shipping_lines_ids
  )
  VALUES (
    source.raw_payload, source.source, source.sheet_kind, source.source_file_id, source.source_file_name,
    source.source_yyyymm, source.source_row_number, source.drive_modified_time, source.row_hash,
    CURRENT_TIMESTAMP(), NULL, JSON_VALUE(source.raw_payload, '$.order_name'),
    JSON_VALUE(source.raw_payload, '$.lineitem_id'), JSON_VALUE(source.raw_payload, '$.lineitem_sku'),
    SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.created_at')),
    SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.updated_at')),
    SAFE.PARSE_TIMESTAMP('%F %T', JSON_VALUE(source.raw_payload, '$.cancelled_at')),
    JSON_VALUE(source.raw_payload, '$.shipping_lines_ids')
  );"""

