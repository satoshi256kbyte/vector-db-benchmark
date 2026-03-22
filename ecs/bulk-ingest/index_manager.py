"""インデックス削除・再作成ロジック."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    import psycopg2.extensions
    from opensearchpy import OpenSearch

logger = structlog.get_logger()

INDEX_NAME = "embeddings"
HNSW_INDEX_NAME = "embeddings_hnsw_idx"
VECTOR_DIMENSION = 1536


class IndexManager(Protocol):
    """インデックス操作の共通インターフェース."""

    def drop_index(self) -> None:
        """インデックスを削除する."""
        ...

    def create_index(self) -> None:
        """インデックスを再作成する."""
        ...


class AuroraIndexManager:
    """Aurora pgvector のインデックス管理.

    HNSWインデックスの削除・再作成とテーブルデータのTRUNCATEを行う。
    """

    def __init__(self, connection: psycopg2.extensions.connection) -> None:
        """AuroraIndexManager を初期化する.

        Args:
            connection: psycopg2 コネクション
        """
        self._connection = connection

    def drop_index(self) -> None:
        """HNSWインデックスを削除し、テーブルデータをTRUNCATEする."""
        log = logger.bind(database="aurora_pgvector")
        log.info("dropping_index", index_name=HNSW_INDEX_NAME)
        with self._connection.cursor() as cur:
            cur.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME};")
            log.info("truncating_table", table_name=INDEX_NAME)
            cur.execute(f"TRUNCATE TABLE {INDEX_NAME};")
        self._connection.commit()
        log.info("drop_index_complete", index_name=HNSW_INDEX_NAME)

    def create_index(self) -> None:
        """HNSWインデックスを再作成する."""
        log = logger.bind(database="aurora_pgvector")
        log.info("creating_index", index_name=HNSW_INDEX_NAME)
        with self._connection.cursor() as cur:
            cur.execute(
                f"CREATE INDEX {HNSW_INDEX_NAME} "
                f"ON {INDEX_NAME} USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64);"
            )
        self._connection.commit()
        log.info("create_index_complete", index_name=HNSW_INDEX_NAME)


class OpenSearchIndexManager:
    """OpenSearch Serverless のインデックス管理.

    OpenSearch Serverless ではインデックスの削除→再作成による性能メリットがないため、
    すべての操作は no-op（ログ出力のみ）となる。
    データ投入は Bulk API で既存インデックスに直接挿入する。
    """

    def __init__(self, client: OpenSearch) -> None:
        """OpenSearchIndexManager を初期化する.

        Args:
            client: OpenSearch クライアント
        """
        self._client = client

    def drop_index(self) -> None:
        """No-op: OpenSearch Serverless ではインデックス削除→再作成の効果がない."""
        log = logger.bind(database="opensearch")
        log.info("drop_index_noop", reason="OpenSearch Serverless does not benefit from index drop/recreate")

    def create_index(self) -> None:
        """No-op: OpenSearch Serverless ではインデックス削除→再作成の効果がない."""
        log = logger.bind(database="opensearch")
        log.info("create_index_noop", reason="OpenSearch Serverless does not benefit from index drop/recreate")


class S3VectorsIndexManager:
    """Amazon S3 Vectors のインデックス管理.

    S3 Vectors にはユーザーが制御可能なインデックスがないため、
    すべての操作は no-op（ログ出力のみ）となる。
    """

    def drop_index(self) -> None:
        """No-op: S3 Vectors にはインデックス削除操作がない."""
        log = logger.bind(database="s3vectors")
        log.info("drop_index_noop", reason="S3 Vectors has no user-controllable index")

    def create_index(self) -> None:
        """No-op: S3 Vectors にはインデックス作成操作がない."""
        log = logger.bind(database="s3vectors")
        log.info("create_index_noop", reason="S3 Vectors has no user-controllable index")
