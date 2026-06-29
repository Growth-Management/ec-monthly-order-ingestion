from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monthly_order_ingestion.audit import build_audit_sql_plan
from monthly_order_ingestion.config import PROJECT_ID, SOURCES
from monthly_order_ingestion.google_clients import build_google_clients


def print_rows(rows: list[bigquery.table.Row]) -> None:
    for row in rows:
        print(dict(row.items()))


def run_select(client: bigquery.Client, sql: str, *, limit: int | None = None) -> list[bigquery.table.Row]:
    if limit is not None:
        sql = f"SELECT * FROM (\n{sql.rstrip(';')}\n)\nLIMIT {limit};"
    return list(client.query(sql).result())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only monthly order lineitem audit queries.")
    parser.add_argument("--source", choices=sorted(SOURCES), help="Optional source filter.")
    parser.add_argument(
        "--query",
        choices=["summary", "details", "cross-month", "ddl"],
        default="summary",
        help="Audit query to print or execute. ddl only prints the proposed result table DDL.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Row limit for details and cross-month outputs.")
    parser.add_argument(
        "--result-table",
        default="ice-ec-project.ice_ec_source.monthly_order_lineitem_audit_results",
        help="Proposed audit result table reference for DDL output.",
    )
    parser.add_argument("--print-sql", action="store_true", help="Print SQL instead of running it.")
    args = parser.parse_args()

    plan = build_audit_sql_plan(args.source, result_table=args.result_table)
    sql_by_query = {
        "summary": plan.summary_sql,
        "details": plan.detail_sql,
        "cross-month": plan.cross_month_sql,
        "ddl": plan.result_table_ddl_sql,
    }
    sql = sql_by_query[args.query]

    if args.print_sql or args.query == "ddl":
        print(sql)
        return

    clients = build_google_clients(PROJECT_ID)
    limit = args.limit if args.query in {"details", "cross-month"} else None
    rows = run_select(clients.bigquery, sql, limit=limit)
    print_rows(rows)


if __name__ == "__main__":
    main()
