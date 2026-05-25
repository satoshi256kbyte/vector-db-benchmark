"""キャッシュストア操作モジュール.

Aurora pgvector 上の semantic_cache テーブルに対する CRUD 操作を提供する。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg2.extensions

from models import CacheEntry


def find_similar(
    connection: psycopg2.extensions.connection,
    query_embedding: list[float],
    threshold: float,
    ttl_seconds: int,
) -> CacheEntry | None:
    """コサイン類似度でキャッシュを検索する.

    TTL超過エントリは除外し、最も類似したエントリを1件取得する。
    類似度が閾値以上の場合のみエントリを返す。

    Args:
        connection: PostgreSQL データベース接続
        query_embedding: クエリ embedding ベクトル（1024次元）
        threshold: キャッシュヒット判定の類似度閾値（0.0〜1.0）
        ttl_seconds: キャッシュエントリの有効期限（秒）

    Returns:
        類似度が閾値以上の CacheEntry、該当なしの場合は None
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
        return None

    row_id, query_text, search_results, created_at, row_ttl_seconds, similarity = row

    if similarity < threshold:
        return None

    # search_results が文字列の場合はパースする
    if isinstance(search_results, str):
        search_results = json.loads(search_results)

    # created_at にタイムゾーン情報がない場合は UTC を付与
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return CacheEntry(
        id=str(row_id),
        query_embedding=query_embedding,
        query_text=query_text,
        search_results=search_results,
        created_at=created_at,
        ttl_seconds=row_ttl_seconds,
    )


def store_entry(
    connection: psycopg2.extensions.connection,
    entry: CacheEntry,
) -> None:
    """キャッシュエントリを保存する.

    Args:
        connection: PostgreSQL データベース接続
        entry: 保存する CacheEntry
    """
    query = """
        INSERT INTO semantic_cache (id, query_embedding, query_text, search_results, created_at, ttl_seconds)
        VALUES (%s, %s::vector, %s, %s::jsonb, %s, %s);
    """
    embedding_str = f"[{','.join(str(v) for v in entry.query_embedding)}]"
    search_results_json = json.dumps(entry.search_results, ensure_ascii=False)

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            (
                entry.id,
                embedding_str,
                entry.query_text,
                search_results_json,
                entry.created_at,
                entry.ttl_seconds,
            ),
        )
    connection.commit()


def cleanup_expired(
    connection: psycopg2.extensions.connection,
    ttl_seconds: int,
) -> int:
    """TTL超過エントリの物理削除を行う.

    超過率が20%を超えた場合のみ実行する。

    Args:
        connection: PostgreSQL データベース接続
        ttl_seconds: キャッシュエントリの有効期限（秒）

    Returns:
        削除件数（超過率20%以下の場合は0）
    """
    count_query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (
                WHERE created_at + (ttl_seconds || ' seconds')::interval <= NOW()
            ) AS expired
        FROM semantic_cache;
    """

    with connection.cursor() as cursor:
        cursor.execute(count_query)
        row = cursor.fetchone()

    if row is None:
        return 0

    total, expired = row

    if total == 0:
        return 0

    expired_ratio = expired / total
    if expired_ratio <= 0.20:
        return 0

    delete_query = """
        DELETE FROM semantic_cache
        WHERE created_at + (ttl_seconds || ' seconds')::interval <= NOW();
    """

    with connection.cursor() as cursor:
        cursor.execute(delete_query)
        deleted_count: int = cursor.rowcount

    connection.commit()

    return deleted_count
