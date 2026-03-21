"""検索テスト Lambda ハンドラー."""

from __future__ import annotations

import json
import traceback

from aws_lambda_powertools import Logger, Tracer

from logic import run_search_test
from models import SearchTestEvent

logger = Logger(service="search-test")
tracer = Tracer(service="search-test")

DEFAULT_SEARCH_COUNT = 100
DEFAULT_TOP_K = 10
DEFAULT_RECORD_COUNT = 100000

MIN_SEARCH_COUNT = 1
MAX_SEARCH_COUNT = 10000
MIN_TOP_K = 1
MAX_TOP_K = 100
MIN_RECORD_COUNT = 1


def _parse_event(event: dict[str, object]) -> SearchTestEvent:
    """イベントペイロードをパースしバリデーションする.

    Args:
        event: Lambda イベント

    Returns:
        SearchTestEvent

    Raises:
        ValueError: パラメータが不正な場合
    """
    search_count = int(event.get("search_count", DEFAULT_SEARCH_COUNT))
    top_k = int(event.get("top_k", DEFAULT_TOP_K))
    record_count = int(event.get("record_count", DEFAULT_RECORD_COUNT))

    if not MIN_SEARCH_COUNT <= search_count <= MAX_SEARCH_COUNT:
        raise ValueError(f"search_count must be between {MIN_SEARCH_COUNT} and {MAX_SEARCH_COUNT}, got {search_count}")
    if not MIN_TOP_K <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}, got {top_k}")
    if record_count < MIN_RECORD_COUNT:
        raise ValueError(f"record_count must be >= {MIN_RECORD_COUNT}, got {record_count}")

    return SearchTestEvent(search_count=search_count, top_k=top_k, record_count=record_count)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict[str, object], context: object) -> dict[str, object]:
    """検索テスト Lambda ハンドラー.

    Args:
        event: Lambda イベント（search_count, top_k, record_count）
        context: Lambda コンテキスト

    Returns:
        検索テスト結果を含むレスポンス
    """
    logger.info("search_test_start", event=event)

    try:
        parsed = _parse_event(event)
    except (ValueError, TypeError) as exc:
        logger.error("invalid_parameters", error=str(exc))
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Invalid parameters: {exc}"}),
        }

    try:
        result = run_search_test(
            search_count=parsed.search_count,
            top_k=parsed.top_k,
            record_count=parsed.record_count,
        )
        logger.info("search_test_complete", search_count=parsed.search_count, top_k=parsed.top_k)
        return {
            "statusCode": 200,
            "body": json.dumps(result.to_dict(), default=str),
        }
    except Exception as exc:
        logger.error("search_test_failed", error=str(exc), traceback=traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Search test failed: {exc}"}),
        }
