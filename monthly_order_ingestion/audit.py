from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from monthly_order_ingestion.config import SOURCES, SheetKind


class AuditClassification(StrEnum):
    AUTO_CORRECTABLE = "auto_correctable"
    NEEDS_REVIEW_NO_MATCHING_INITIAL_ORDER_SKU = "needs_review_no_matching_initial_order_sku"
    NEEDS_REVIEW_NON_UNIQUE_INITIAL_LINEITEM = "needs_review_non_unique_initial_lineitem"
    TARGET_NO_MISMATCH = "target_no_mismatch"
    OUT_OF_SCOPE = "out_of_scope"


AUDIT_RESULT_COLUMNS = [
    "source",
    "sheet_type",
    "order_name",
    "observed_lineitem_sku",
    "observed_lineitem_id",
    "expected_initial_lineitem_id",
    "baseline_lineitem_ids",
    "observed_source_yyyymm",
    "initial_order_yyyymm",
    "involved_months",
    "order_month_count",
    "shipping_month_count",
    "order_shipping_month_count",
    "cancel_row_count",
    "expired_row_count",
    "source_file_id",
    "source_file_name",
    "source_row_number",
    "row_hash",
    "created_at",
    "updated_at",
    "cancelled_at",
    "audit_classification",
    "audited_at",
]


@dataclass(frozen=True)
class AuditSqlPlan:
    summary_sql: str
    detail_sql: str
    cross_month_sql: str
    result_table_ddl_sql: str
    result_table_insert_sql: str


def _source_items(source: str | None):
    if source is None:
        return SOURCES.items()
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    return [(source, SOURCES[source])]


def _all_rows_cte(source: str | None = None) -> str:
    selects: list[str] = []
    for source_name, source_config in _source_items(source):
        for kind in SheetKind:
            table = source_config.tables[kind].main
            selects.append(
                "\n".join(
                    [
                        f"SELECT '{source_name}' AS source, '{kind.value}' AS sheet_type,",
                        "  order_name, lineitem_id, lineitem_sku, created_at, updated_at, cancelled_at,",
                        "  source_yyyymm, source_file_id, source_file_name, source_row_number, row_hash",
                        f"FROM `{table}`",
                    ]
                )
            )
    return "WITH all_rows AS (\n" + "\nUNION ALL\n".join(selects) + "\n)"


def audit_base_ctes(source: str | None = None) -> str:
    return f"""{_all_rows_cte(source)},
order_line_baseline AS (
  SELECT
    source,
    order_name,
    lineitem_sku,
    COUNT(DISTINCT lineitem_id) AS baseline_lineitem_id_count,
    ARRAY_AGG(DISTINCT lineitem_id IGNORE NULLS ORDER BY lineitem_id) AS baseline_lineitem_ids,
    ARRAY_AGG(
      STRUCT(lineitem_id, created_at, source_yyyymm, source_file_name, source_row_number)
      ORDER BY created_at ASC, source_yyyymm ASC, source_row_number ASC
      LIMIT 1
    )[OFFSET(0)] AS first_order_line
  FROM all_rows
  WHERE sheet_type = 'order'
    AND order_name IS NOT NULL AND order_name != ''
    AND lineitem_sku IS NOT NULL AND lineitem_sku != ''
  GROUP BY source, order_name, lineitem_sku
),
order_month_flags AS (
  SELECT
    source,
    order_name,
    COUNT(DISTINCT IF(sheet_type = 'order', source_yyyymm, NULL)) AS order_month_count,
    COUNT(DISTINCT IF(sheet_type = 'shipping', source_yyyymm, NULL)) AS shipping_month_count,
    COUNT(DISTINCT IF(sheet_type IN ('order', 'shipping'), source_yyyymm, NULL)) AS order_shipping_month_count,
    COUNTIF(sheet_type = 'cancel') AS cancel_row_count,
    COUNTIF(sheet_type = 'expired') AS expired_row_count,
    ARRAY_AGG(DISTINCT source_yyyymm ORDER BY source_yyyymm) AS involved_months
  FROM all_rows
  WHERE order_name IS NOT NULL AND order_name != ''
  GROUP BY source, order_name
),
audit_rows AS (
  SELECT
    r.source,
    r.sheet_type,
    r.order_name,
    r.lineitem_sku AS observed_lineitem_sku,
    r.lineitem_id AS observed_lineitem_id,
    b.first_order_line.lineitem_id AS expected_initial_lineitem_id,
    b.baseline_lineitem_ids,
    r.source_yyyymm AS observed_source_yyyymm,
    b.first_order_line.source_yyyymm AS initial_order_yyyymm,
    f.involved_months,
    f.order_month_count,
    f.shipping_month_count,
    f.order_shipping_month_count,
    f.cancel_row_count,
    f.expired_row_count,
    r.source_file_id,
    r.source_file_name,
    r.source_row_number,
    r.row_hash,
    r.created_at,
    r.updated_at,
    r.cancelled_at,
    CASE
      WHEN b.order_name IS NULL THEN '{AuditClassification.NEEDS_REVIEW_NO_MATCHING_INITIAL_ORDER_SKU.value}'
      WHEN b.baseline_lineitem_id_count != 1 THEN '{AuditClassification.NEEDS_REVIEW_NON_UNIQUE_INITIAL_LINEITEM.value}'
      WHEN r.lineitem_id != b.first_order_line.lineitem_id THEN '{AuditClassification.AUTO_CORRECTABLE.value}'
      WHEN f.order_shipping_month_count >= 2
        AND f.order_month_count > 0
        AND f.shipping_month_count > 0
        AND f.cancel_row_count > 0 THEN '{AuditClassification.TARGET_NO_MISMATCH.value}'
      ELSE '{AuditClassification.OUT_OF_SCOPE.value}'
    END AS audit_classification,
    CURRENT_TIMESTAMP() AS audited_at
  FROM all_rows r
  LEFT JOIN order_line_baseline b
    ON r.source = b.source
   AND r.order_name = b.order_name
   AND r.lineitem_sku = b.lineitem_sku
  JOIN order_month_flags f
    ON r.source = f.source
   AND r.order_name = f.order_name
  WHERE r.sheet_type IN ('shipping', 'cancel', 'expired')
)"""


def cross_month_candidate_sql(source: str | None = None) -> str:
    return f"""{audit_base_ctes(source)}
SELECT
  source,
  order_name,
  involved_months,
  order_month_count,
  shipping_month_count,
  order_shipping_month_count,
  cancel_row_count,
  expired_row_count
FROM order_month_flags
WHERE order_shipping_month_count >= 2
  AND order_month_count > 0
  AND shipping_month_count > 0
ORDER BY source, order_name;"""


def lineitem_mismatch_detail_sql(source: str | None = None, *, include_out_of_scope: bool = False) -> str:
    where = "" if include_out_of_scope else f"WHERE audit_classification != '{AuditClassification.OUT_OF_SCOPE.value}'"
    return f"""{audit_base_ctes(source)}
SELECT
  {",\n  ".join(AUDIT_RESULT_COLUMNS)}
FROM audit_rows
{where}
ORDER BY
  CASE audit_classification
    WHEN '{AuditClassification.AUTO_CORRECTABLE.value}' THEN 1
    WHEN '{AuditClassification.NEEDS_REVIEW_NO_MATCHING_INITIAL_ORDER_SKU.value}' THEN 2
    WHEN '{AuditClassification.NEEDS_REVIEW_NON_UNIQUE_INITIAL_LINEITEM.value}' THEN 3
    WHEN '{AuditClassification.TARGET_NO_MISMATCH.value}' THEN 4
    ELSE 5
  END,
  source,
  order_name,
  sheet_type,
  source_row_number;"""


def audit_summary_sql(source: str | None = None) -> str:
    return f"""{audit_base_ctes(source)}
SELECT
  source,
  sheet_type,
  audit_classification,
  COUNT(*) AS candidate_row_count,
  COUNT(DISTINCT order_name) AS candidate_order_count,
  COUNTIF(order_shipping_month_count >= 2 AND order_month_count > 0 AND shipping_month_count > 0) AS cross_month_order_shipping_row_count,
  COUNTIF(order_shipping_month_count >= 2 AND order_month_count > 0 AND shipping_month_count > 0 AND cancel_row_count > 0) AS cross_month_with_cancel_row_count
FROM audit_rows
GROUP BY source, sheet_type, audit_classification
ORDER BY source, sheet_type, audit_classification;"""


def create_audit_result_table_sql(table_ref: str) -> str:
    return f"""CREATE TABLE IF NOT EXISTS `{table_ref}` (
  source STRING NOT NULL,
  sheet_type STRING NOT NULL,
  order_name STRING,
  observed_lineitem_sku STRING,
  observed_lineitem_id STRING,
  expected_initial_lineitem_id STRING,
  baseline_lineitem_ids ARRAY<STRING>,
  observed_source_yyyymm STRING,
  initial_order_yyyymm STRING,
  involved_months ARRAY<STRING>,
  order_month_count INT64,
  shipping_month_count INT64,
  order_shipping_month_count INT64,
  cancel_row_count INT64,
  expired_row_count INT64,
  source_file_id STRING,
  source_file_name STRING,
  source_row_number INT64,
  row_hash STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  cancelled_at TIMESTAMP,
  audit_classification STRING NOT NULL,
  audited_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(audited_at)
CLUSTER BY source, audit_classification, order_name, observed_source_yyyymm;"""


def insert_audit_results_sql(table_ref: str, source: str | None = None) -> str:
    return f"""{audit_base_ctes(source)}
INSERT INTO `{table_ref}` (
  {",\n  ".join(AUDIT_RESULT_COLUMNS)}
)
SELECT
  {",\n  ".join(AUDIT_RESULT_COLUMNS)}
FROM audit_rows
WHERE audit_classification != '{AuditClassification.OUT_OF_SCOPE.value}';"""


def build_audit_sql_plan(
    source: str | None = None,
    *,
    result_table: str = "ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results",
) -> AuditSqlPlan:
    return AuditSqlPlan(
        summary_sql=audit_summary_sql(source),
        detail_sql=lineitem_mismatch_detail_sql(source),
        cross_month_sql=cross_month_candidate_sql(source),
        result_table_ddl_sql=create_audit_result_table_sql(result_table),
        result_table_insert_sql=insert_audit_results_sql(result_table, source),
    )
