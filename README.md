# ec-monthly-order-ingestion

Drive 上の `monthly_order_YYYYMM` Google Sheets を BigQuery に取り込むための運用リポジトリです。

## 対象

- source: `pta`, `fabli`
- Drive file name: `^monthly_order_\d{6}$` に完全一致する Google Sheets
- sheet: `注文`, `出荷`, `キャンセル`, `期限切れ`
- BigQuery project: `ice-ec-project`
- BigQuery dataset: `ice_ec_source`

`作業用`、`.xlsx`、`.csv`、`出荷データ用`、`修正後` などを含む派生ファイルは取り込み対象外です。

## 実行

初回または過去分の差分取り込み:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/spreadsheets.readonly

python scripts/run_monthly_order_ingestion.py \
  --mode delta \
  --from-yyyymm 202207
```

通常運用では `--mode delta` を使います。manifest に成功記録がないファイル、または Drive `modifiedTime` が前回取り込み時より新しいファイルだけ処理します。

## 監査

月またぎ注文・出荷、およびキャンセルに伴う商品情報変更による `lineitem_id` 差異を確認します。

```bash
python scripts/run_monthly_order_audit.py --query summary
python scripts/run_monthly_order_audit.py --source pta --query details --limit 200
```

DDL や監査結果保存用 INSERT は SQL 表示のみです。実行が必要な場合は、出力 SQL を GCP コンソール上で確認してから実行します。

```bash
python scripts/run_monthly_order_audit.py --query ddl
python scripts/run_monthly_order_audit.py --query insert
```

詳細は [docs/lineitem_audit_ja.md](docs/lineitem_audit_ja.md) を参照してください。
GCP コンソールで実行する SQL は [docs/gcp_console_audit_sql_ja.md](docs/gcp_console_audit_sql_ja.md) を参照してください。

## 自動転送

Cloud Run Jobs + Cloud Scheduler で運用します。

- Cloud Run Job: `scripts/run_monthly_order_ingestion.py --mode delta`
- Cloud Scheduler: 日次などの定期実行
- Drive / Sheets 読み取り: Secret Manager に保存した篠原アカウントの authorized user token
- BigQuery 書き込み: Cloud Run Job のサービスアカウント
- 0行シートも manifest に `success` / `row_count = 0` を記録

詳細は [docs/full_load_and_automation_ja.md](docs/full_load_and_automation_ja.md) を参照してください。

## テスト

```bash
python tests/run_unit_tests.py
```