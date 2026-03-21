"""検索テスト Lambda ハンドラー."""

from __future__ import annotations

from aws_lambda_powertools import Logger, Tracer

logger = Logger(service="search-test")
tracer = Tracer(service="search-test")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict[str, object], context: object) -> dict[str, object]:
    """Lambda ハンドラー（後続タスクで実装）."""
    logger.info("search_test_start")
    return {"statusCode": 200, "body": "not implemented"}
