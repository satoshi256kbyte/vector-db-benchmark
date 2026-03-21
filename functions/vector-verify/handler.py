"""動作確認Lambda ハンドラー.

Aurora (pgvector)、OpenSearch Serverless、および Amazon S3 Vectors の
動作確認を実行し、結果を VerifyResponse として JSON で返却する。
"""

from __future__ import annotations

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from logic import (
    VECTOR_COUNT,
    VECTOR_DIMENSION,
    generate_dummy_vectors,
    run_aurora_verify,
    run_opensearch_verify,
    run_s3vectors_verify,
)
from models import DatabaseResult, VerifyResponse

logger = Logger(service="vector-verify")
tracer = Tracer(service="vector-verify")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    """動作確認Lambda のエントリポイント.

    ダミーベクトルを生成し、Aurora、OpenSearch、S3 Vectors それぞれに対して
    独立して動作確認を実行する。1つが失敗しても他は継続する。

    Args:
        event: Lambda イベントペイロード
        context: Lambda コンテキスト

    Returns:
        VerifyResponse を辞書化した JSON レスポンス
    """
    logger.info("動作確認開始", extra={"dimension": VECTOR_DIMENSION, "count": VECTOR_COUNT})

    vectors = generate_dummy_vectors(VECTOR_COUNT, VECTOR_DIMENSION)
    query_vector = generate_dummy_vectors(1, VECTOR_DIMENSION)[0]

    # Aurora 動作確認（独立実行）
    aurora_result: DatabaseResult
    try:
        aurora_result = run_aurora_verify(vectors, query_vector)
    except Exception:  # noqa: BLE001
        logger.exception("Aurora 動作確認で予期しないエラー")
        aurora_result = DatabaseResult(
            database="aurora_pgvector",
            insert_count=0,
            search_result_count=0,
            success=False,
            error_message="予期しないエラーが発生しました",
        )

    # OpenSearch 動作確認（独立実行）
    opensearch_result: DatabaseResult
    try:
        opensearch_result = run_opensearch_verify(vectors, query_vector)
    except Exception:  # noqa: BLE001
        logger.exception("OpenSearch 動作確認で予期しないエラー")
        opensearch_result = DatabaseResult(
            database="opensearch",
            insert_count=0,
            search_result_count=0,
            success=False,
            error_message="予期しないエラーが発生しました",
        )

    # S3 Vectors 動作確認（独立実行）
    s3vectors_result: DatabaseResult
    try:
        s3vectors_result = run_s3vectors_verify(vectors, query_vector)
    except Exception:  # noqa: BLE001
        logger.exception("S3 Vectors 動作確認で予期しないエラー")
        s3vectors_result = DatabaseResult(
            database="s3vectors",
            insert_count=0,
            search_result_count=0,
            success=False,
            error_message="予期しないエラーが発生しました",
        )

    response = VerifyResponse(
        aurora=aurora_result,
        opensearch=opensearch_result,
        s3vectors=s3vectors_result,
        vector_dimension=VECTOR_DIMENSION,
        total_vectors=VECTOR_COUNT,
    )

    logger.info(
        "動作確認完了",
        extra={
            "aurora_success": aurora_result.success,
            "opensearch_success": opensearch_result.success,
            "s3vectors_success": s3vectors_result.success,
        },
    )

    return response.to_dict()
