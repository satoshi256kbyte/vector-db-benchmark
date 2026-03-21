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

    HNSWマッピング付きインデックスの削除・再作成を行う。
    """

    def __init__(self, client: OpenSearch) -> None:
        """OpenSearchIndexManager を初期化する.

        Args:
            client: OpenSearch クライアント
        """
        self._client = client

    def drop_index(self) -> None:
        """OpenSearch インデックスを削除する（存在しない場合は無視）."""
        log = logger.bind(database="opensearch")
        log.info("dropping_index", index_name=INDEX_NAME)
        self._client.indices.delete(index=INDEX_NAME, ignore=[404])
        log.info("drop_index_complete", index_name=INDEX_NAME)

    def create_index(self) -> None:
        """HNSWマッピング付きで OpenSearch インデックスを再作成する."""
        log = logger.bind(database="opensearch")
        log.info("creating_index", index_name=INDEX_NAME)
        body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100,
                },
            },
            "mappings": {
                "properties": {
                    "id": {"type": "integer"},
                    "content": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": VECTOR_DIMENSION,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "faiss",
                            "parameters": {"m": 16, "ef_construction": 64},
                        },
                    },
                },
            },
        }
        self._client.indices.create(index=INDEX_NAME, body=body)
        log.info("create_index_complete", index_name=INDEX_NAME)


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
