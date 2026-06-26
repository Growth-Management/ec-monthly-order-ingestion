from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable


KNOWN_HEADER_MAP = {
    "Order Name": "order_name",
    "Created At": "created_at",
    "Total": "total",
    "Subtotal": "subtotal",
    "Total Taxes": "total_taxes",
    "Shipping Lines Total Price (include Discount)": "shipping_lines_total_price_include_discount",
    "Total Lineitems Quantity": "total_lineitems_quantity",
    "Financial Status": "financial_status",
    "Fulfillment Status": "fulfillment_status",
    "Currency": "currency",
    "Current Total Price": "current_total_price",
    "Current Subtotal Price": "current_subtotal_price",
    "Current Total Tax": "current_total_tax",
    "Payment Gateway Name": "payment_gateway_name",
    "Customer ID": "customer_id",
    "Lineitem ID": "lineitem_id",
    "Lineitem Product ID": "lineitem_product_id",
    "Lineitem SKU": "lineitem_sku",
    "Lineitem Title": "lineitem_title",
    "Lineitem Price": "lineitem_price",
    "Lineitem Variant Compare At Price": "lineitem_variant_compare_at_price",
    "Lineitem Discount Allocations Discount Group Code": "lineitem_discount_allocations_discount_group_code",
    "Lineitem Discount Allocations Discount Codes": "lineitem_discount_allocations_discount_codes",
    "Lineitem Discount Allocations Total Amount": "lineitem_discount_allocations_total_amount",
    "Lineitem Tax Lines Prices": "lineitem_tax_lines_prices",
    "Lineitem Tax Lines Rates": "lineitem_tax_lines_rates",
    "Lineitem Quantity": "lineitem_quantity",
    "Lineitem Fulfilled Quantity": "lineitem_fulfilled_quantity",
    "Lineitem Refunded Quantity": "lineitem_refunded_quantity",
    "Lineitem Fulfillment Status": "lineitem_fulfillment_status",
    "Shipping Lines Codes": "shipping_lines_codes",
    "Shipping Lines IDs": "shipping_lines_ids",
    "Lineitem Last Successful Fulfillment Date": "lineitem_last_successful_fulfillment_date",
    "Transactions Authorization": "transactions_authorization",
    "Updated At": "updated_at",
    "Cancelled At": "cancelled_at",
    "Last Refund Date": "last_refund_date",
    "Lineitem Variant Option 1": "lineitem_variant_option_1",
    "Lineitem Variant Option 2": "lineitem_variant_option_2",
    "Lineitem Variant Option 3": "lineitem_variant_option_3",
    "Business Code": "business_code",
    "Lineitem Variant Inventory Item Cost": "lineitem_variant_inventory_item_cost",
    "Lineitem Current Vendor": "lineitem_current_vendor",
    "Lineitem Product Type": "lineitem_product_type",
    "Lineitem Product Option": "lineitem_product_option",
    "Customer Orders Count": "customer_orders_count",
    "Discount Codes": "discount_codes",
    "Discount Codes (Code)": "discount_codes_code",
}

INGESTION_COLUMNS = {
    "source",
    "sheet_kind",
    "source_file_id",
    "source_file_name",
    "source_yyyymm",
    "source_row_number",
    "drive_modified_time",
    "row_hash",
    "ingested_at",
    "updated_ingestion_at",
}


def snake_case_header(header: Any) -> str:
    value = "" if header is None else str(header).strip()
    if value in KNOWN_HEADER_MAP:
        return KNOWN_HEADER_MAP[value]
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unnamed"


def normalize_headers(headers: Iterable[Any]) -> list[str]:
    base_headers = [snake_case_header(header) for header in headers]
    counts: Counter[str] = Counter()
    normalized: list[str] = []
    for header in base_headers:
        counts[header] += 1
        normalized.append(header if counts[header] == 1 else f"{header}_{counts[header]}")
    return normalized


def canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped == "" else stripped
    return value


def row_hash(row: dict[str, Any]) -> str:
    payload = {
        key: canonical_value(value)
        for key, value in row.items()
        if key not in {"row_hash", "ingested_at", "updated_ingestion_at"}
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_rows(
    values: list[list[Any]],
    *,
    source: str,
    sheet_kind: str,
    source_file_id: str,
    source_file_name: str,
    source_yyyymm: str,
    drive_modified_time: str,
) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = normalize_headers(values[0])
    rows: list[dict[str, Any]] = []
    for zero_based_index, raw_row in enumerate(values[1:], start=1):
        if not any(canonical_value(value) is not None for value in raw_row):
            continue
        row = {
            header: canonical_value(raw_row[column_index]) if column_index < len(raw_row) else None
            for column_index, header in enumerate(headers)
        }
        row.update(
            {
                "source": source,
                "sheet_kind": sheet_kind,
                "source_file_id": source_file_id,
                "source_file_name": source_file_name,
                "source_yyyymm": source_yyyymm,
                "source_row_number": zero_based_index + 1,
                "drive_modified_time": drive_modified_time,
            }
        )
        row["row_hash"] = row_hash(row)
        rows.append(row)
    return rows
