"""セマンティックキャッシュ制御モジュール.

キャッシュルックアップ → ヒット/ミス判定 → Aurora検索 → キャッシュ書き込みの
フロー制御を行う。キャッシュ障害時は透過的にバイパスし、検索機能の可用性を維持する。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg2.extensions
from aws_lambda_powertools import Logger

from cache_store import find_similar, store_entry
from logic import search_aurora  # noqa: F401 - Aurora検索のインターフェース参照
from models import CacheEntry

logger = Logger(service="search-test")


@dataclass
class CacheResult:
    """キャッシュ処理結果.

    Attributes:
        hit: キャッシュヒット判定
        similarity_score: コサイン類似度スコア（ミス/バイパス時はNone）
        results: 検索結果リスト（検索失敗時はNone）
        lookup_time_ms: キャッシュルックアップ所要時間（ミリ秒）
        source: 結果の取得元（"cache" | "aurora" | "bypass"）
    """

    hit: bool
    similarity_score: float | None
    results: list[dict[str, object]] | None
    lookup_time_ms: float
    source: str  # "cache" | "aurora" | "bypass"


def _find_similar_with_score(
    connection: psycopg2.extensions.connection,
    query_embedding: list[float],
    threshold: float,
    ttl_seconds: int,
) -> tuple[CacheEntry | None, float | None]:
    """コサイン類似度でキャッシュを検索し、類似度スコアも返す.

    Args:
        connection: PostgreSQL データベース接続
        query_embedding: クエリ embedding ベクトル（1024次元）
        threshold: キャッシュヒット判定の類似度閾値（0.0〜1.0）
        ttl_seconds: キャッシュエントリの有効期限（秒）

    Returns:
        (CacheEntry | None, similarity_score | None) のタプル
    """
    query = """
        SELECT id, query_text, search_results, created_at, ttl_seconds,
               1 - (query_embedding <=> %s::vector) AS similarity
        FROM semantic_cache
        WHERE created_at + (ttl_seconds || ' seconds')::interval > NOW()
        ORDER BY query_embedding <=> %s::vector
        LIMIT 1;
    """
    embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

    with connection.cursor() as cursor:
        cursor.execute(query, (embedding_str, embedding_str))
        row = cursor.fetchone()

    if row is None:
        return None, None

    row_id, query_text, search_results, created_at, row_ttl_seconds, similarity = row

    if similarity < threshold:
        return None, float(similarity)

    # search_results が文字列の場合はパースする
    if isinstance(search_results, str):
        search_results = json.loads(search_results)

    # created_at にタイムゾーン情報がない場合は UTC を付与
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    entry = CacheEntry(
        id=str(row_id),
        query_embedding=query_embedding,
        query_text=query_text,
        search_results=search_results,
        created_at=created_at,
        ttl_seconds=row_ttl_seconds,
    )
    return entry, float(similarity)


def _write_cache(
    connection: psycopg2.extensions.connection,
    query_text: str,
    query_embedding: list[float],
    search_results: list[dict[str, object]],
    ttl_seconds: int,
) -> None:
    """キャッシュエントリを書き込む（非同期実行用）.

    Args:
        connection: PostgreSQL データベース接続
        query_text: 元のクエリテキスト
        query_embedding: クエリ embedding ベクトル
        search_results: 検索結果
        ttl_seconds: キャッシュ有効期限（秒）
    """
    try:
        entry = CacheEntry(
            id=str(uuid.uuid4()),
            query_embedding=query_embedding,
            query_text=query_text,
            search_results=search_results,
            created_at=datetime.now(tz=timezone.utc),
            ttl_seconds=ttl_seconds,
        )
        store_entry(connection, entry)
        logger.info("cache_write_success", query_text=query_text[:50])
    except Exception as exc:
        logger.error(
            "cache_write_failed",
            error=str(exc),
            query_text=query_text[:50],
            action="continue_without_cache",
        )


def _search_aurora_results(
    connection: psycopg2.extensions.connection,
    query_embedding: list[float],
    top_k: int,
) -> list[dict[str, object]]:
    """Aurora pgvector から検索結果を取得する.

    Args:
        connection: PostgreSQL データベース接続
        query_embedding: クエリ embedding ベクトル
        top_k: 返却件数

    Returns:
        検索結果のリスト（各要素は content と distance を含む辞書）

    Raises:
        Exception: Aurora 検索に失敗した場合
    """
    query = (
        "SELECT content, embedding <=> %s::vector AS distance "
        "FROM embeddings ORDER BY distance LIMIT %s;"
    )
    embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

    with connection.cursor() as cur:
        cur.execute(query, (embedding_str, top_k))
        rows = cur.fetchall()

    results: list[dict[str, object]] = []
    for row in rows:
        results.append({"content": row[0], "distance": float(row[1])})
    return results


def lookup_and_search(
    query_text: str,
    query_embedding: list[float],
    connection: psycopg2.extensions.connection,
    threshold: float,
    top_k: int,
    ttl_seconds: int = 3600,
) -> CacheResult:
    """キャッシュルックアップ → ヒット/ミス判定 → 必要に応じてAurora検索.

    キャッシュ障害時は透過的にバイパスし、Aurora 直接検索にフォールバックする。
    キャッシュミス時の書き込みは非同期で行い、レスポンス返却をブロックしない。

    Args:
        query_text: 検索クエリテキスト
        query_embedding: クエリ embedding ベクトル（1024次元）
        connection: PostgreSQL データベース接続
        threshold: キャッシュヒット判定の類似度閾値（0.0〜1.0）
        top_k: Aurora 検索時の返却件数
        ttl_seconds: キャッシュエントリの有効期限（秒、デフォルト3600）

    Returns:
        CacheResult（ヒット/ミス判定、類似度スコア、検索結果、所要時間、取得元）
    """
    # --- キャッシュルックアップ ---
    lookup_start = time.monotonic()
    try:
        cached_entry, similarity_score = _find_similar_with_score(
            connection=connection,
            query_embedding=query_embedding,
            threshold=threshold,
            ttl_seconds=ttl_seconds,
        )
        lookup_time_ms = (time.monotonic() - lookup_start) * 1000
    except Exception as exc:
        lookup_time_ms = (time.monotonic() - lookup_start) * 1000
        logger.error(
            "cache_lookup_failed",
            error=str(exc),
            query_text=query_text[:50],
            action="bypass_to_aurora",
        )
        # キャッシュ障害時: Aurora 直接検索にバイパス
        try:
            results = _search_aurora_results(connection, query_embedding, top_k)
        except Exception as search_exc:
            logger.error("aurora_search_failed_on_bypass", error=str(search_exc))
            results = None
        return CacheResult(
            hit=False,
            similarity_score=None,
            results=results,
            lookup_time_ms=lookup_time_ms,
            source="bypass",
        )

    # --- キャッシュヒット ---
    if cached_entry is not None:
        logger.info(
            "cache_hit",
            query_text=query_text[:50],
            similarity_score=round(similarity_score, 4) if similarity_score else None,
            lookup_time_ms=round(lookup_time_ms, 2),
        )
        return CacheResult(
            hit=True,
            similarity_score=similarity_score,
            results=cached_entry.search_results,
            lookup_time_ms=lookup_time_ms,
            source="cache",
        )

    # --- キャッシュミス: Aurora 検索 ---
    logger.info(
        "cache_miss",
        query_text=query_text[:50],
        similarity_score=round(similarity_score, 4) if similarity_score else None,
        lookup_time_ms=round(lookup_time_ms, 2),
    )
    try:
        results = _search_aurora_results(connection, query_embedding, top_k)
    except Exception as search_exc:
        logger.error("aurora_search_failed", error=str(search_exc))
        return CacheResult(
            hit=False,
            similarity_score=similarity_score,
            results=None,
            lookup_time_ms=lookup_time_ms,
            source="aurora",
        )

    # --- 非同期キャッシュ書き込み ---
    write_thread = threading.Thread(
        target=_write_cache,
        args=(connection, query_text, query_embedding, results, ttl_seconds),
        daemon=True,
    )
    write_thread.start()

    return CacheResult(
        hit=False,
        similarity_score=similarity_score,
        results=results,
        lookup_time_ms=lookup_time_ms,
        source="aurora",
    )
