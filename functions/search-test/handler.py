"""検索テスト Lambda ハンドラー."""

from __future__ import annotations

import json
import os
import time
import traceback

from aws_lambda_powertools import Logger, Tracer

from embedding import EmbeddingError, generate_embedding
from logic import _get_aurora_connection, run_search_test
from metrics import SearchMetrics, log_search_metrics
from models import CacheMetadata, SearchTestEvent, SemanticCacheResponse
from semantic_cache import lookup_and_search

logger = Logger(service="search-test")
tracer = Tracer(service="search-test")

_MIN_QUERY_LENGTH = 1
_MAX_QUERY_LENGTH = 1000
_DEFAULT_SIMILARITY_THRESHOLD = 0.95
_DEFAULT_CACHE_TTL = 3600
_DEFAULT_TOP_K = 5

DEFAULT_SEARCH_COUNT = 100
DEFAULT_SEARCH_TOP_K = 10
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
    top_k = int(event.get("top_k", DEFAULT_SEARCH_TOP_K))
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


def _get_config() -> tuple[float, int]:
    """環境変数からセマンティックキャッシュ設定を読み込む.

    Returns:
        (similarity_threshold, cache_ttl) のタプル

    Notes:
        環境変数が未設定の場合はデフォルト値を使用する。
        - SIMILARITY_THRESHOLD: 0.95
        - CACHE_TTL: 3600
    """
    threshold_str = os.environ.get("SIMILARITY_THRESHOLD", "")
    ttl_str = os.environ.get("CACHE_TTL", "")

    if threshold_str:
        similarity_threshold = float(threshold_str)
    else:
        similarity_threshold = _DEFAULT_SIMILARITY_THRESHOLD

    if ttl_str:
        cache_ttl = int(ttl_str)
    else:
        cache_ttl = _DEFAULT_CACHE_TTL

    return similarity_threshold, cache_ttl


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def semantic_cache_handler(event: dict[str, object], context: object) -> dict[str, object]:
    """セマンティックキャッシュ経由の検索ハンドラー.

    テキストクエリを受け取り、セマンティックキャッシュ経由で Aurora pgvector を検索する。
    キャッシュヒット時はキャッシュから結果を返却し、ミス時は Aurora 検索後にキャッシュに書き込む。

    Args:
        event: {"query": "検索テキスト"}
        context: Lambda コンテキスト

    Returns:
        {
            "statusCode": 200,
            "body": {
                "results": [...],
                "cache": {
                    "hit": true/false,
                    "similarity_score": 0.97,
                    "lookup_time_ms": 5.2
                },
                "metrics": {
                    "total_time_ms": 15.3,
                    "embedding_time_ms": 8.1,
                    "search_time_ms": null,
                    "cache_write_time_ms": null
                }
            }
        }
    """
    total_start = time.monotonic()
    logger.info("semantic_cache_handler_start", event=event)

    # --- 入力バリデーション ---
    query = event.get("query", "")
    if not isinstance(query, str):
        query = str(query)

    if len(query) < _MIN_QUERY_LENGTH or len(query) > _MAX_QUERY_LENGTH:
        logger.warning(
            "validation_error",
            query_length=len(query),
            min_length=_MIN_QUERY_LENGTH,
            max_length=_MAX_QUERY_LENGTH,
        )
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": f"query must be between {_MIN_QUERY_LENGTH} and {_MAX_QUERY_LENGTH} characters, "
                f"got {len(query)}",
            }),
        }

    # --- 設定読み込み ---
    similarity_threshold, cache_ttl = _get_config()
    logger.info(
        "config_loaded",
        similarity_threshold=similarity_threshold,
        cache_ttl=cache_ttl,
    )

    # --- Embedding 生成 ---
    embedding_time_ms: float | None = None
    search_time_ms: float | None = None
    cache_write_time_ms: float | None = None
    bypass_to_aurora = False

    try:
        embedding_result = generate_embedding(query)
        embedding_time_ms = embedding_result.time_ms
        query_embedding = embedding_result.embedding
    except EmbeddingError as exc:
        logger.error(
            "embedding_failed",
            error=str(exc),
            query_text=query[:50],
            action="bypass_to_aurora",
        )
        bypass_to_aurora = True

    # --- キャッシュバイパス（Embedding 失敗時）: Aurora 直接検索 ---
    if bypass_to_aurora:
        try:
            connection = _get_aurora_connection()
            search_start = time.monotonic()
            with connection.cursor() as cur:
                embedding_for_search = [0.0] * 1024  # ダミーベクトル（直接検索不可のためエラー）
                cur.execute(
                    "SELECT content, embedding <=> %s::vector AS distance "
                    "FROM embeddings ORDER BY distance LIMIT %s;",
                    (f"[{','.join(str(v) for v in embedding_for_search)}]", _DEFAULT_TOP_K),
                )
                rows = cur.fetchall()
            search_time_ms = (time.monotonic() - search_start) * 1000
            connection.close()

            results: list[dict[str, object]] = [
                {"content": row[0], "distance": float(row[1])} for row in rows
            ]
            total_time_ms = (time.monotonic() - total_start) * 1000

            metrics = SearchMetrics(
                total_time_ms=total_time_ms,
                embedding_time_ms=None,
                lookup_time_ms=None,
                search_time_ms=search_time_ms,
                cache_write_time_ms=None,
                cache_hit=False,
                similarity_score=None,
            )
            log_search_metrics(metrics)

            response = SemanticCacheResponse(
                results=results,
                cache=CacheMetadata(hit=False, similarity_score=None, lookup_time_ms=0.0),
                metrics=metrics,
            )
            return {
                "statusCode": 200,
                "body": json.dumps(response.to_dict(), default=str),
            }
        except Exception as exc:
            logger.error("aurora_search_failed_on_bypass", error=str(exc))
            total_time_ms = (time.monotonic() - total_start) * 1000
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Search failed: {exc}"}),
            }

    # --- キャッシュルックアップ → Aurora 検索 ---
    try:
        connection = _get_aurora_connection()
        search_start = time.monotonic()
        cache_result = lookup_and_search(
            query_text=query,
            query_embedding=query_embedding,
            connection=connection,
            threshold=similarity_threshold,
            top_k=_DEFAULT_TOP_K,
            ttl_seconds=cache_ttl,
        )
        if not cache_result.hit and cache_result.source == "aurora":
            search_time_ms = (time.monotonic() - search_start) * 1000 - cache_result.lookup_time_ms
        connection.close()
    except Exception as exc:
        logger.error("search_failed", error=str(exc), traceback=traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Search failed: {exc}"}),
        }

    # --- レスポンス構築 ---
    total_time_ms = (time.monotonic() - total_start) * 1000

    if cache_result.results is None:
        logger.error("search_returned_no_results", source=cache_result.source)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Search returned no results"}),
        }

    metrics = SearchMetrics(
        total_time_ms=total_time_ms,
        embedding_time_ms=embedding_time_ms,
        lookup_time_ms=cache_result.lookup_time_ms,
        search_time_ms=search_time_ms,
        cache_write_time_ms=cache_write_time_ms,
        cache_hit=cache_result.hit,
        similarity_score=cache_result.similarity_score,
    )
    log_search_metrics(metrics)

    response = SemanticCacheResponse(
        results=cache_result.results,
        cache=CacheMetadata(
            hit=cache_result.hit,
            similarity_score=cache_result.similarity_score,
            lookup_time_ms=cache_result.lookup_time_ms,
        ),
        metrics=metrics,
    )

    logger.info(
        "semantic_cache_handler_complete",
        cache_hit=cache_result.hit,
        similarity_score=cache_result.similarity_score,
        total_time_ms=round(total_time_ms, 2),
    )

    return {
        "statusCode": 200,
        "body": json.dumps(response.to_dict(), default=str),
    }
