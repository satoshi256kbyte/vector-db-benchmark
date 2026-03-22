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

    def ensure_table(self) -> None:
        """pgvector 拡張の有効化と embeddings テーブルの自動作成を行う.

        冪等に動作し、拡張・テーブルが既に存在する場合はスキップされる。
        """
        log = logger.bind(database="aurora_pgvector")
        log.info("ensuring_table", table_name=INDEX_NAME)
        with self._connection.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            log.info("pgvector_extension_ensured")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {INDEX_NAME} "
                f"(content TEXT, embedding vector({VECTOR_DIMENSION}));"
            )
            log.info("table_ensured", table_name=INDEX_NAME)
        self._connection.commit()

    def drop_index(self) -> None:
        """HNSWインデックスを削除し、テーブルデータをTRUNCATEする."""
        log = logger.bind(database="aurora_pgvector")
        log.info("dropping_index", index_name=HNSW_INDEX_NAME)
        with self._connection.cursor() as cur:
            cur.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME};")
            cur.execute(
                f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{INDEX_NAME}');"
            )
            table_exists = cur.fetchone()[0]
            if table_exists:
                log.info("truncating_table", table_name=INDEX_NAME)
                cur.execute(f"TRUNCATE TABLE {INDEX_NAME};")
            else:
                log.info("table_not_found_skipping_truncate", table_name=INDEX_NAME)
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
    drop_index / create_index は no-op（ログ出力のみ）となる。
    データ投入は Bulk API で既存インデックスに直接挿入する。
    """

    def __init__(self, client: OpenSearch) -> None:
        """OpenSearchIndexManager を初期化する.

        Args:
            client: OpenSearch クライアント
        """
        self._client = client

    def ensure_index(self) -> None:
        """embeddings インデックスが存在しない場合に作成する.

        既存インデックスのマッピングが期待と異なる場合は削除して再作成する。
        冪等に動作し、正しいマッピングが既に存在する場合はスキップされる。
        """
        log = logger.bind(database="opensearch")
        if self._client.indices.exists(index=INDEX_NAME):
            # マッピングが期待通りか検証する
            if self._is_mapping_compatible():
                log.info("index_already_exists", index_name=INDEX_NAME)
                return
            log.warning(
                "index_mapping_incompatible",
                index_name=INDEX_NAME,
                action="delete_and_recreate",
            )
            self._client.indices.delete(index=INDEX_NAME)
            log.info("index_deleted_for_recreate", index_name=INDEX_NAME)

        log.info("creating_index", index_name=INDEX_NAME)
        body = self._index_body()
        self._client.indices.create(index=INDEX_NAME, body=body)
        log.info("index_created", index_name=INDEX_NAME)

    def _is_mapping_compatible(self) -> bool:
        """既存インデックスの embedding フィールドが knn_vector かどうかを検証する.

        Returns:
            マッピングが互換であれば True
        """
        log = logger.bind(database="opensearch")
        try:
            mapping = self._client.indices.get_mapping(index=INDEX_NAME)
            props = mapping[INDEX_NAME]["mappings"].get("properties", {})
            emb = props.get("embedding", {})
            emb_type = emb.get("type")
            is_compatible = emb_type == "knn_vector"
            if not is_compatible:
                log.info("mapping_check_detail", embedding_type=emb_type, expected="knn_vector")
            return is_compatible
        except Exception as e:
            log.warning("mapping_check_failed", error=str(e))
            return False

    @staticmethod
    def _index_body() -> dict[str, object]:
        """embeddings インデックスのボディ定義を返す."""
        return {
            "settings": {
                "index": {
                    "knn": True,
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
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 128,
                                "m": 16,
                            },
                        },
                    },
                },
            },
        }

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
