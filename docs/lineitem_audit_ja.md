# 月次注文 lineitem_id 監査

## 最終目的

最終的に楽々販売へ投入しているデータについて、これまで運用側が手動で補正してきた内容を BigQuery 上で再現できる状態にします。

本リポジトリでの監査・補正ロジックの目的は、運用側ヒアリングで確定する投入ルールを待ちながら、同様の補正済みデータを生成・検証できるところまで進めることです。

## 監査目的

月次注文取り込み後に、月またぎの注文・出荷、およびキャンセルに伴う商品情報変更によって `lineitem_id` が変わる可能性があるレコードを監査します。

正しい `lineitem_id` は原則として注文時の初期値です。キャンセル後レコードや出荷レコード側の `lineitem_id` を根拠なく正とみなさず、初期注文行から一意に特定できる場合だけ補正候補にします。

## 補正データの格納方針

`ice_ec_source` の取り込み元テーブルは更新しません。監査証跡として source 層をそのまま保持します。

補正後データは `ice_ec_aggregation` dataset に別テーブルとして作成します。まず pta の shipping だけを検証対象にし、以下のテーブルへ格納します。

`ice-ec-project.ice_ec_aggregation.monthly_shipping_pta_lineitem_corrected`

この補正後テーブルでは、元の shipping 行を全件保持し、レビュー承認された補正対象だけ以下を更新します。

- `lineitem_id`
- `raw_payload.lineitem_id`
- `updated_ingestion_at`

加えて、補正監査用の列を追加します。

- `original_lineitem_id`
- `corrected_lineitem_id`
- `lineitem_id_corrected`
- `lineitem_correction_classification`
- `lineitem_correction_reason`
- `lineitem_correction_audited_at`

## 対象テーブル

- pta
  - `ice-ec-project.ice_ec_source.monthly_order_pta`
  - `ice-ec-project.ice_ec_source.monthly_shipping_pta`
  - `ice-ec-project.ice_ec_source.monthly_cancel_pta`
  - `ice-ec-project.ice_ec_source.monthly_expired_pta`
- fabli
  - `ice-ec-project.ice_ec_source.monthly_order_fabli`
  - `ice-ec-project.ice_ec_source.monthly_shipping_fabli`
  - `ice-ec-project.ice_ec_source.monthly_cancel_fabli`
  - `ice-ec-project.ice_ec_source.monthly_expired_fabli`

## 分類

- `auto_correctable`
  - `order_name + lineitem_sku` で初期注文行が見つかる
  - 初期注文側の `lineitem_id` が一意
  - 対象行の `lineitem_id` が初期注文時の `lineitem_id` と異なる
- `needs_review_no_matching_initial_order_sku`
  - 対象行の `order_name + lineitem_sku` に対応する初期注文行が見つからない
  - 商品情報変更、SKU 欠落、または初期注文側データ欠落の可能性があるため自動確定しない
- `needs_review_non_unique_initial_lineitem`
  - 初期注文側の `order_name + lineitem_sku` に複数の `lineitem_id` がある
  - どれを正とするか一意に決まらないため自動確定しない
- `target_no_mismatch`
  - 月またぎ注文・出荷 + キャンセルありの重点監査対象だが、初期注文時の `lineitem_id` と不一致はない
- `out_of_scope`
  - 上記に該当しない通常行
  - 監査結果テーブルへ保存する INSERT SQL では除外する

## audit_reason

`audit_classification` は大分類、`audit_reason` は要確認理由です。

- `unique_initial_order_sku_lineitem_mismatch`
  - 初期注文 SKU は一意だが、対象行の `lineitem_id` が異なる
- `unique_initial_order_sku_no_mismatch`
  - 初期注文 SKU は一意で、`lineitem_id` の不一致はない
- `non_unique_initial_lineitem_for_order_sku`
  - `order_name + lineitem_sku` に複数の初期 `lineitem_id` があり、一意に補正できない
- `observed_sku_blank`
  - 対象行側の SKU が空欄
- `no_initial_order_for_order_name`
  - 注文テーブル側に同じ `order_name` がない
- `observed_lineitem_id_exists_in_initial_order_with_different_or_blank_sku`
  - 対象行の `lineitem_id` は注文テーブルに存在するが、SKU が違う、または空欄
- `single_initial_lineitem_but_sku_changed`
  - 同じ `order_name` の初期注文行が 1 明細だけなので候補は見えるが、SKU が一致しないため自動確定しない
- `multi_initial_lineitems_sku_changed_or_missing`
  - 同じ `order_name` に複数の初期注文明細があり、SKU 不一致のため補正先を一意に決められない

## BigQuery 確認方針

テーブル schema 確認と件数・分布確認は BigQuery MCP の読み取りで行います。
DDL や監査結果保存用 INSERT が必要な場合、このリポジトリでは SQL を生成するだけです。実行は GCP コンソール上で内容確認後に行います。

## 実行例

summary を BigQuery に対して読み取り実行します。

```bash
python scripts/run_monthly_order_audit.py --query summary
```

source を絞る場合:

```bash
python scripts/run_monthly_order_audit.py --source pta --query summary
python scripts/run_monthly_order_audit.py --source fabli --query details --limit 200
```

SQL だけ確認する場合:

```bash
python scripts/run_monthly_order_audit.py --source pta --query details --print-sql
python scripts/run_monthly_order_audit.py --query cross-month --print-sql
```

GCP コンソールで実行する DDL を出力します。コマンドは SQL 表示のみで、DDL は実行しません。

```bash
python scripts/run_monthly_order_audit.py --query ddl
```

監査結果テーブルへ保存する INSERT SQL を出力します。コマンドは SQL 表示のみで、INSERT は実行しません。

```bash
python scripts/run_monthly_order_audit.py --query insert
```

## 監査結果テーブル案

既定の保存先案:

`ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results`

設計:

- partition: `DATE(audited_at)`
- cluster: `source, audit_classification, audit_reason, order_name`
- 保存対象: `out_of_scope` 以外

DDL レビュー観点:

- `audit_reason` を必須列にして、要確認理由を後追いできるようにする
- `initial_order_lineitem_ids` / `initial_order_skus` を配列で保持し、要確認行の候補を監査結果だけで確認できるようにする
- `observed_lineitem_id_exists_in_initial_order` を保持し、SKU だけが違うケースを切り分ける
- `expected_initial_lineitem_id` は `order_name + lineitem_sku` で一意に特定できた場合の値に限定する

## 現時点の BigQuery MCP 読み取り確認結果

2026-06-29 JST 時点の確認です。

対象テーブル件数:

| source | sheet | rows |
| --- | --- | ---: |
| pta | order | 32,061 |
| pta | shipping | 30,238 |
| pta | cancel | 750 |
| pta | expired | 114 |
| fabli | order | 4,126 |
| fabli | shipping | 3,162 |
| fabli | cancel | 145 |
| fabli | expired | 89 |

空値確認:

- `order_name` 空値: 全対象テーブル 0 件
- `lineitem_id` 空値: 全対象テーブル 0 件

重点候補:

| source | metric | count |
| --- | --- | ---: |
| pta | 月またぎ注文・出荷あり order | 8,372 |
| pta | 月またぎ注文・出荷 + キャンセルあり order | 52 |
| fabli | 月またぎ注文・出荷あり order | 2,539 |
| fabli | 月またぎ注文・出荷 + キャンセルあり order | 1 |

保守的な `order_name + lineitem_sku` 突合での初期分類:

- `auto_correctable`: 0 件
- pta `needs_review_no_matching_initial_order_sku`: 162 行
- pta `needs_review_non_unique_initial_lineitem`: 47 行
- fabli `needs_review_no_matching_initial_order_sku`: 159 行

`needs_review_no_matching_initial_order_sku` の理由別内訳:

| source | sheet | audit_reason | rows |
| --- | --- | --- | ---: |
| fabli | cancel | `no_initial_order_for_order_name` | 14 |
| fabli | expired | `no_initial_order_for_order_name` | 8 |
| fabli | shipping | `no_initial_order_for_order_name` | 137 |
| pta | cancel | `no_initial_order_for_order_name` | 1 |
| pta | cancel | `observed_sku_blank` | 2 |
| pta | shipping | `multi_initial_lineitems_sku_changed_or_missing` | 4 |
| pta | shipping | `no_initial_order_for_order_name` | 149 |
| pta | shipping | `observed_sku_blank` | 1 |
| pta | shipping | `single_initial_lineitem_but_sku_changed` | 5 |

## pta 補正後テーブル検証結果

GCP コンソールで `ice_ec_aggregation.monthly_shipping_pta_lineitem_corrected` を作成後、BigQuery MCP で読み取り確認しました。

| check | result |
| --- | ---: |
| total rows | 30,238 |
| corrected rows | 5 |
| original_lineitem_id rows | 5 |
| corrected lineitem_id matches correction reference | 5 |
| raw_payload.lineitem_id matches correction reference | 5 |
| rows differing from source monthly_shipping_pta | 5 |

補正済み 5 行:

| order_name | original_lineitem_id | corrected_lineitem_id | shipping_yyyymm | initial_order_yyyymm |
| --- | ---: | ---: | --- | --- |
| pTa-16543 | 15001785762017 | 14978830237921 | 202508 | 202506 |
| pTa-22105 | 15910321520865 | 15873515323617 | 202603 | 202601 |
| pTa-22168 | 15904308363489 | 15880636170465 | 202602 | 202601 |
| pTa-23846 | 16578045051105 | 16570221166817 | 202606 | 202605 |
| pTa-2559 | 13042825527521 | 13040940581089 | 202311 | 202307 |

## 残タスク: 楽々販売投入データ再現軸

### 1. 運用側ヒアリング結果の回収

- 楽々販売投入前に手動補正している項目を確認する
- `lineitem_id` が変わるケースで、運用側がどの ID を正としているか確認する
- SKU 変更・商品情報変更がある場合の判断基準を確認する
- 複数初期注文明細候補がある場合の手動判断基準を確認する
- 注文テーブルに同じ `order_name` が見つからないケースの扱いを確認する
- fabli の `no_initial_order_for_order_name` を投入対象として扱うか確認する

### 2. BigQuery で補正済みデータを生成する

- pta shipping の補正済みテーブルは作成済み
- pta の `single_initial_lineitem_but_sku_changed` 5 件は補正済みデータとして反映済み
- pta の `multi_initial_lineitems_sku_changed_or_missing` 4 件を、運用側ルールに基づいて補正可否判断する
- `no_initial_order_for_order_name` の扱いを、投入対象外・過去注文欠落・別 source 参照などに分類する
- fabli は補正 0 件として複製テーブルを作るか、必要時のみ作るか判断する

### 3. 楽々販売投入データ相当の出力を設計する

- 楽々販売へ投入している現行ファイル / テーブル / カラム定義を確認する
- pta 補正後 shipping を使って、楽々販売投入データ相当の中間テーブルを設計する
- テーブル名案を決める
  - 例: `ice_ec_aggregation.rakuraku_sales_pta_prepared`
- fabli も同じ粒度で必要か確認する
- 出力列、主キー、集計粒度、日付基準を整理する

### 4. 手動補正結果と BigQuery 生成結果を突合する

- 運用側から手動補正済みデータまたは投入ファイルを受領する
- BigQuery 生成結果と手動補正済みデータを突合する
- 差分を `補正ルール不足` / `データ欠落` / `対象外` / `要運用判断` に分類する
- 再現率と未解決件数を報告する

### 5. 運用化判断

- 手動 GCP コンソール実行を継続するか判断する
- Cloud Run Job / Scheduler / TROCCO などへ組み込むか判断する
- 楽々販売投入直前の検証 SQL を整備する
- PR #4 をレビュー・マージする
- 最終運用手順を Notion / GitHub docs に反映する
