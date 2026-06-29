# 月次注文 lineitem_id 監査

## 目的

月次注文取り込み後に、月またぎの注文・出荷、およびキャンセルに伴う商品情報変更によって `lineitem_id` が変わる可能性があるレコードを監査します。

正しい `lineitem_id` は原則として注文時の初期値です。キャンセル後レコードや出荷レコード側の `lineitem_id` を根拠なく正とみなさず、初期注文行から一意に特定できる場合だけ補正候補にします。

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

2026-06-29 JST 時点の確認です。DDL や書き込みは実行していません。

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

## 次の実装候補

1. 監査結果保存テーブルを GCP コンソールで作成する。
2. Cloud Run Job に監査 runner を追加するか、取り込み job の後続ステップとして summary/details を実行する。
3. `no_initial_order_for_order_name` が出る月の注文ファイル取り込み範囲や source_yyyymm を確認する。
4. `single_initial_lineitem_but_sku_changed` は補正候補に近いが、自動補正ではなくレビュー承認後に扱う。
5. `auto_correctable` が出た場合の補正 SQL は、監査結果確認後に別途レビュー付きで作成する。
