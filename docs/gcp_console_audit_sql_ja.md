# GCP コンソール実行用 SQL: 月次注文 lineitem_id 監査

このファイルは GCP コンソールで実行する SQL を明示するためのものです。
このリポジトリの runner や BigQuery MCP では DDL/DML/書き込みを実行しません。

## 事前確認

BigQuery MCP の dataset table list では、2026-06-29 時点で以下のテーブルは未作成です。

`ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results`

## 1. 監査結果テーブル作成 DDL

目的:

- 月次注文監査結果を保存する
- `audit_classification` と `audit_reason` で自動補正可能・要確認・対象外相当を切り分ける
- 初期注文側候補を配列で保持し、監査結果だけで確認できるようにする

GCP コンソールで実行する SQL:

```sql
CREATE TABLE IF NOT EXISTS `ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results` (
  source STRING NOT NULL,
  sheet_type STRING NOT NULL,
  order_name STRING,
  observed_lineitem_sku STRING,
  observed_lineitem_id STRING,
  expected_initial_lineitem_id STRING,
  baseline_lineitem_ids ARRAY<STRING>,
  initial_order_lineitem_id_count INT64,
  initial_order_sku_count INT64,
  initial_order_lineitem_ids ARRAY<STRING>,
  initial_order_skus ARRAY<STRING>,
  observed_lineitem_id_exists_in_initial_order BOOL,
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
  audit_reason STRING NOT NULL,
  audited_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(audited_at)
CLUSTER BY source, audit_classification, audit_reason, order_name;
```

## 2. DDL 実行後確認 SQL

目的:

- テーブルが作成されたことを確認する
- partition / clustering と主要列が想定どおりか確認する

GCP コンソールまたは BigQuery MCP の読み取りで確認する SQL:

```sql
SELECT
  table_name,
  table_type,
  creation_time
FROM `ice-ec-project.ice_ec_source.INFORMATION_SCHEMA.TABLES`
WHERE table_name = 'monthly_order_lineitem_audit_results';
```

```sql
SELECT
  column_name,
  data_type,
  is_nullable,
  clustering_ordinal_position
FROM `ice-ec-project.ice_ec_source.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'monthly_order_lineitem_audit_results'
ORDER BY ordinal_position;
```

```sql
SELECT
  table_name,
  ddl
FROM `ice-ec-project.ice_ec_source.INFORMATION_SCHEMA.TABLES`
WHERE table_name = 'monthly_order_lineitem_audit_results';
```

## 3. 監査結果 INSERT SQL の生成方法

監査結果保存用 INSERT は長いため、PR 内の runner で SQL を生成して GCP コンソールに貼り付けます。
このコマンドは SQL を表示するだけで、INSERT は実行しません。

```bash
python scripts/run_monthly_order_audit.py --query insert
```

source ごとに分けて保存する場合:

```bash
python scripts/run_monthly_order_audit.py --source pta --query insert
python scripts/run_monthly_order_audit.py --source fabli --query insert
```

## 4. INSERT 実行前の読み取り確認 SQL

INSERT 前に同じ分類が想定どおり出ているか確認します。
この確認は BigQuery MCP の読み取りでも実行できます。

```bash
python scripts/run_monthly_order_audit.py --query summary
python scripts/run_monthly_order_audit.py --source pta --query summary
python scripts/run_monthly_order_audit.py --source fabli --query summary
```

## 5. INSERT 実行後確認 SQL

目的:

- 保存結果に `out_of_scope` が混ざっていないこと
- source / sheet / classification / reason 別の件数を確認すること

```sql
SELECT
  COUNT(*) AS row_count,
  COUNTIF(audit_classification = 'out_of_scope') AS out_of_scope_rows,
  MIN(audited_at) AS min_audited_at,
  MAX(audited_at) AS max_audited_at
FROM `ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results`
WHERE DATE(audited_at) = CURRENT_DATE();
```

```sql
SELECT
  source,
  sheet_type,
  audit_classification,
  audit_reason,
  COUNT(*) AS row_count,
  COUNT(DISTINCT order_name) AS order_count
FROM `ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results`
WHERE DATE(audited_at) = CURRENT_DATE()
GROUP BY source, sheet_type, audit_classification, audit_reason
ORDER BY source, sheet_type, audit_classification, audit_reason;
```

```sql
SELECT
  source,
  sheet_type,
  order_name,
  observed_lineitem_sku,
  observed_lineitem_id,
  expected_initial_lineitem_id,
  audit_classification,
  audit_reason,
  initial_order_lineitem_ids,
  initial_order_skus,
  involved_months,
  source_file_name,
  source_row_number
FROM `ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results`
WHERE DATE(audited_at) = CURRENT_DATE()
  AND audit_classification IN (
    'auto_correctable',
    'needs_review_no_matching_initial_order_sku',
    'needs_review_non_unique_initial_lineitem'
  )
ORDER BY
  CASE audit_classification
    WHEN 'auto_correctable' THEN 1
    WHEN 'needs_review_no_matching_initial_order_sku' THEN 2
    WHEN 'needs_review_non_unique_initial_lineitem' THEN 3
    ELSE 4
  END,
  source,
  order_name,
  sheet_type,
  source_row_number
LIMIT 200;
```

## 注意

- DDL は `CREATE TABLE IF NOT EXISTS` のため、同名テーブルが存在する場合は既存 schema を変更しません。
- 既存テーブルがある状態で schema 変更が必要になった場合は、別途 `ALTER TABLE` または再作成手順をレビューしてから実行します。
- INSERT は重複防止をまだ持たないため、同じ日に複数回保存する場合は `audited_at` ごとの結果が追加されます。
