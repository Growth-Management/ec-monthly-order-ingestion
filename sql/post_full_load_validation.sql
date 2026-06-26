-- Post full-load validation for monthly_order ingestion.

-- 1. Manifest status summary.
WITH manifests AS (
  SELECT 'pta' AS source, 'order' AS sheet_kind, source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'shipping', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'cancel', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'expired', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_pta_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'order', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'shipping', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'cancel', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'expired', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_fabli_ingestion_manifest`
)
SELECT
  source,
  sheet_kind,
  status,
  COUNT(*) AS file_sheet_count,
  SUM(IFNULL(row_count, 0)) AS manifest_row_count,
  MAX(last_ingested_at) AS latest_ingested_at
FROM manifests
GROUP BY source, sheet_kind, status
ORDER BY source, sheet_kind, status;

-- 2. Manifest errors.
WITH manifests AS (
  SELECT 'pta' AS source, 'order' AS sheet_kind, source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'shipping', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'cancel', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'expired', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_pta_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'order', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'shipping', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'cancel', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'expired', source_yyyymm, source_file_id, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_fabli_ingestion_manifest`
)
SELECT *
FROM manifests
WHERE status != 'success'
ORDER BY source, source_yyyymm, sheet_kind, source_file_name;

-- 3. Main row counts by month.
WITH main_rows AS (
  SELECT 'pta' AS source, 'order' AS sheet_kind, source_yyyymm, COUNT(*) AS row_count
  FROM `ice-ec-project.ice_ec_source.monthly_order_pta`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'pta', 'shipping', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_pta`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'pta', 'cancel', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_pta`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'pta', 'expired', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_expired_pta`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'fabli', 'order', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_order_fabli`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'fabli', 'shipping', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_fabli`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'fabli', 'cancel', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_fabli`
  GROUP BY source_yyyymm
  UNION ALL
  SELECT 'fabli', 'expired', source_yyyymm, COUNT(*)
  FROM `ice-ec-project.ice_ec_source.monthly_expired_fabli`
  GROUP BY source_yyyymm
)
SELECT *
FROM main_rows
ORDER BY source, source_yyyymm, sheet_kind;
