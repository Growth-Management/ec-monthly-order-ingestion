from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_monthly_order_ingestion import (  # noqa: E402
    test_cancel_fallback_key_uses_updated_at_and_source_row_number,
    test_bigquery_execution_plan_includes_success_and_error_manifest_sql,
    test_decide_ingestion_uses_successful_manifest_modified_time,
    test_authorized_user_info_supports_json_env,
    test_execute_with_retry_retries_connection_reset,
    test_manifest_success_zero_rows_sql_uses_literal_target_metadata,
    test_normalize_headers_known_and_duplicate_names,
    test_normalize_rows_serializes_dates_from_xlsx,
    test_normalize_rows_adds_common_columns_and_stable_hash,
    test_primary_key_validation_sql_uses_sheet_kind_key_candidates,
    test_required_sheet_selection,
    test_select_target_files_requires_exact_name_and_google_sheet,
    test_staging_record_splits_raw_payload_and_common_columns,
)


def main() -> None:
    tests = [
        test_select_target_files_requires_exact_name_and_google_sheet,
        test_decide_ingestion_uses_successful_manifest_modified_time,
        test_authorized_user_info_supports_json_env,
        test_execute_with_retry_retries_connection_reset,
        test_required_sheet_selection,
        test_normalize_headers_known_and_duplicate_names,
        test_normalize_rows_adds_common_columns_and_stable_hash,
        test_normalize_rows_serializes_dates_from_xlsx,
        test_staging_record_splits_raw_payload_and_common_columns,
        test_primary_key_validation_sql_uses_sheet_kind_key_candidates,
        test_bigquery_execution_plan_includes_success_and_error_manifest_sql,
        test_cancel_fallback_key_uses_updated_at_and_source_row_number,
        test_manifest_success_zero_rows_sql_uses_literal_target_metadata,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")


if __name__ == "__main__":
    main()
