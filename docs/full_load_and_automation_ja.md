# 既存データ全量アップロードと自動転送の実行手順

## 現在の状態

`monthly_order_202606` は以下まで完了済み。

- pta / fabli の staging load
- MERGE
- manifest success 更新
- source 混在チェック
- manifest success 確認

監査へ進む前に、既存の過去月ファイルを全量取り込み、その後は Drive `modifiedTime` ベースで差分転送できる状態にする。

## 対象ファイルのルール

Drive フォルダ内で以下に完全一致する Google Sheets だけを対象にする。

```text
^monthly_order_\d{6}$
```

`作業用`、`xlsx`、`csv`、`出荷データ用`、`修正後` などを含む派生ファイルは対象外。

## 1. Cloud Shell で既存データ全量ロードを実行する

Cloud Shell にこの作業ディレクトリ一式を配置したうえで実行する。

初回だけ依存関係を入れる。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Drive 読み取りと BigQuery 書き込みに使う Application Default Credentials を設定する。

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly
```

既存データを取り込む。`delta` は manifest を見て、未登録または Drive `modifiedTime` が進んだファイルだけ処理する。すでに完了した 202606 はスキップされる。

```bash
python scripts/run_monthly_order_ingestion.py \
  --mode delta \
  --from-yyyymm 202207
```

特定 source だけ実行する場合:

```bash
python scripts/run_monthly_order_ingestion.py \
  --source pta \
  --mode delta \
  --from-yyyymm 202207
```

特定範囲だけ実行する場合:

```bash
python scripts/run_monthly_order_ingestion.py \
  --mode delta \
  --from-yyyymm 202501 \
  --to-yyyymm 202605
```

すべて再処理したい場合のみ `--mode full` を使う。

```bash
python scripts/run_monthly_order_ingestion.py \
  --mode full \
  --from-yyyymm 202207
```

## 2. 実行後の確認

manifest の error を確認する。

```sql
WITH manifests AS (
  SELECT 'pta' AS source, 'order' AS sheet_kind, source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'shipping', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'cancel', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_pta_ingestion_manifest`
  UNION ALL
  SELECT 'pta', 'expired', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_pta_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'order', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_order_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'shipping', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_shipping_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'cancel', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_cancel_fabli_ingestion_manifest`
  UNION ALL
  SELECT 'fabli', 'expired', source_yyyymm, source_file_name, row_count, status, error_message, last_ingested_at
  FROM `ice-ec-project.ice_ec_source.monthly_expired_fabli_ingestion_manifest`
)
SELECT *
FROM manifests
WHERE status != 'success'
ORDER BY source, source_yyyymm, sheet_kind;
```

0 行なら、manifest 上の失敗はなし。

## 3. 自動転送の仕組み

自動転送は Cloud Run Jobs + Cloud Scheduler で運用する。

- Cloud Run Job: `scripts/run_monthly_order_ingestion.py --mode delta` を実行するバッチ。
- Cloud Scheduler: Cloud Run Job を定期実行する。
- Drive `modifiedTime` と manifest を比較し、未登録または更新済みファイルだけ処理する。

Google の公式ドキュメントでも、Cloud Run Jobs は完了して終了するジョブ実行、Cloud Scheduler は Cloud Run Job のスケジュール実行に使える構成として案内されている。

## 4. サービスアカウント準備

例:

```bash
PROJECT_ID="ice-ec-project"
SA_NAME="monthly-order-ingestion"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name "Monthly order Drive to BigQuery ingestion"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/bigquery.jobUser"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/bigquery.dataEditor"
```

Drive 側では、pta / fabli の対象フォルダをこのサービスアカウントのメールアドレスに共有する。

```text
pta folder:   1GJ8Z3gKTb9h8nG6n01amNbM4Ortkxe64
fabli folder: 1GfVxojNBBLKd-E0q1c58ysaxc00lGQ8j
```

## 5. Cloud Run Job としてデプロイする

```bash
PROJECT_ID="ice-ec-project"
REGION="asia-northeast1"
SA_EMAIL="monthly-order-ingestion@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run jobs deploy monthly-order-ingestion \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --service-account "${SA_EMAIL}" \
  --max-retries 0 \
  --task-timeout 24h \
  --command python \
  --args scripts/run_monthly_order_ingestion.py,--mode,delta
```

手動実行テスト:

```bash
gcloud run jobs execute monthly-order-ingestion \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --wait
```

## 6. スケジュール設定

Cloud Console で以下を設定する。

1. Cloud Run > Jobs を開く。
2. `monthly-order-ingestion` を選ぶ。
3. Triggers タブを開く。
4. Add Scheduler Trigger を選ぶ。
5. 毎日または毎月の実行時刻を設定する。

推奨:

```text
毎日 07:00 JST
```

月次ファイルの更新が月初以外にも起きるため、日次で差分だけ拾う運用が安全。

## 7. 運用上の注意

- `--mode delta` を通常運用に使う。
- `--mode full` は再処理が必要なときだけ使う。
- キャンセルシートは fallback key `order_name + lineitem_id + updated_at + source_row_number` を使用する。
- 0行シートも manifest に `success` / `row_count = 0` を残す。
- 1ファイルまたは1シートで失敗しても、他のシート処理は継続し、失敗は manifest に `error` として残す。
