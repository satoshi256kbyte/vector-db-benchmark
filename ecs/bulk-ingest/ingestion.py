"""DB別データ投入ロジック."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

import structlog

from vector_generator import generate_vector

if TYPE_CHECKING:
    import psycopg2.extensions
    from mypy_boto3_s3vectors import S3VectorsClient
    from opensearchpy import OpenSearch

logger = structlog.get_logger()

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class Ingester(Protocol):
    """データ投入の共通インターフェース."""

    def ingest_batch(self, start_index: int, end_index: int) -> int:
        """指定範囲のレコードをバッチ投入する.

        Args:
            start_index: 開始インデックス（含む）
            end_index: 終了インデックス（含まない）

        Returns:
            投入したレコード数
        """
        ...

    def ingest_all(self, record_count: int, batch_size: int = 1000) -> int:
        """全レコードをバッチ単位で投入する.

        Args:
            record_count: 投入するレコード総数
            batch_size: 1バッチあたりのレコード数

        Returns:
            投入したレコード総数
        """
        ...


class AuroraIngester:
    """Aurora pgvector へのバッチ INSERT によるデータ投入.

    1000件単位のバッチ INSERT で効率的にベクトルデータを投入する。
    """

    def __init__(self, connection: psycopg2.extensions.connection) -> None:
        """AuroraIngester を初期化する.

        Args:
            connection: psycopg2 コネクション
        """
        self._connection = connection

    def ingest_batch(self, start_index: int, end_index: int) -> int:
        """指定範囲のレコードをバッチ INSERT で投入する.

        Args:
            start_index: 開始インデックス（含む）
            end_index: 終了インデックス（含まない）

        Returns:
            投入したレコード数
        """
        values_parts: list[str] = []
        params: list[str | list[float]] = []
        for i in range(start_index, end_index):
            values_parts.append("(%s, %s::vector)")
            params.append(f"doc-{i}")
            params.append(generate_vector(seed=i))

        sql = f"INSERT INTO embeddings (content, embedding) VALUES {', '.join(values_parts)};"
        with self._connection.cursor() as cur:
            cur.execute(sql, params)
        self._connection.commit()
        return end_index - start_index

    def ingest_all(self, record_count: int, batch_size: int = 500) -> int:
        """全レコードをバッチ単位で Aurora に投入する.

        Args:
            record_count: 投入するレコード総数
            batch_size: 1バッチあたりのレコード数（デフォルト500件）

        Returns:
            投入したレコード総数
        """
        log = logger.bind(database="aurora_pgvector")
        total_inserted = 0

        for start in range(0, record_count, batch_size):
            end = min(start + batch_size, record_count)
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    count = self.ingest_batch(start, end)
                    total_inserted += count
                    break
                except Exception as e:
                    log.warning("batch_insert_retry", start=start, end=end, attempt=attempt, error=str(e))
                    if attempt == MAX_RETRIES:
                        log.error("batch_insert_failed", start=start, end=end, error=str(e))
                        break
                    time.sleep(RETRY_DELAY_SECONDS)

        log.info("ingest_all_complete", total_inserted=total_inserted)
        return total_inserted


class OpenSearchIngester:
    """OpenSearch Serverless への Bulk API によるデータ投入."""

    def __init__(self, client: OpenSearch) -> None:
        """OpenSearchIngester を初期化する.

        Args:
            client: OpenSearch クライアント
        """
        self._client = client

    def ingest_batch(self, start_index: int, end_index: int) -> int:
        """指定範囲のレコードを Bulk API で投入する.

        Args:
            start_index: 開始インデックス（含む）
            end_index: 終了インデックス（含まない）

        Returns:
            投入したレコード数
        """
        bulk_body: list[dict[str, object]] = []
        for i in range(start_index, end_index):
            # OpenSearch Serverless VECTOR コレクションでは _id 指定不可
            bulk_body.append({"index": {"_index": "embeddings"}})
            bulk_body.append({"id": i, "content": f"doc-{i}", "embedding": generate_vector(seed=i)})

        response = self._client.bulk(body=bulk_body)
        if response.get("errors"):
            error_items = [item for item in response["items"] if "error" in item.get("index", {})]
            # 最初のエラー詳細をログに含める
            first_error = ""
            if error_items:
                first_error = str(error_items[0].get("index", {}).get("error", ""))
            raise RuntimeError(
                f"OpenSearch bulk API returned errors: {len(error_items)} items failed, first_error={first_error}"
            )
        return end_index - start_index

    def ingest_all(self, record_count: int, batch_size: int = 1000) -> int:
        """全レコードをバッチ単位で OpenSearch に投入する.

        Args:
            record_count: 投入するレコード総数
            batch_size: 1バッチあたりのレコード数

        Returns:
            投入したレコード総数
        """
        log = logger.bind(database="opensearch")
        total_inserted = 0

        for start in range(0, record_count, batch_size):
            end = min(start + batch_size, record_count)
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    count = self.ingest_batch(start, end)
                    total_inserted += count
                    break
                except Exception as e:
                    log.warning("batch_insert_retry", start=start, end=end, attempt=attempt, error=str(e))
                    if attempt == MAX_RETRIES:
                        log.error("batch_insert_failed", start=start, end=end, error=str(e))
                        break
                    time.sleep(RETRY_DELAY_SECONDS)

        log.info("ingest_all_complete", total_inserted=total_inserted)
        return total_inserted


class S3VectorsIngester:
    """Amazon S3 Vectors への PutVectors API によるデータ投入."""

    def __init__(self, client: S3VectorsClient, bucket_name: str, index_name: str) -> None:
        """S3VectorsIngester を初期化する.

        Args:
            client: boto3 s3vectors クライアント
            bucket_name: S3 Vectors バケット名
            index_name: S3 Vectors インデックス名
        """
        self._client = client
        self._bucket_name = bucket_name
        self._index_name = index_name

    def ingest_batch(self, start_index: int, end_index: int) -> int:
        """指定範囲のレコードを PutVectors API で投入する.

        Args:
            start_index: 開始インデックス（含む）
            end_index: 終了インデックス（含まない）

        Returns:
            投入したレコード数
        """
        vectors: list[dict[str, object]] = []
        for i in range(start_index, end_index):
            vectors.append({
                "key": str(i),
                "data": {"float32": generate_vector(seed=i)},
                "metadata": {"content": f"doc-{i}"},
            })

        self._client.put_vectors(
            vectorBucketName=self._bucket_name,
            indexName=self._index_name,
            vectors=vectors,
        )
        return end_index - start_index

    def ingest_all(self, record_count: int, batch_size: int = 200) -> int:
        """全レコードをバッチ単位で S3 Vectors に投入する.

        S3 Vectors の PutVectors API は1回あたり最大500件かつリクエストペイロード
        最大 20MiB の制限がある。1536次元 float32 ベクトル（約6KB/件）の場合、
        200件でも約1.3MB 程度であり API 制限の範囲内のため、デフォルトバッチサイズ
        を200件に設定。旧デフォルト（50件）では 100,000件投入時に 2,000回の API
        コールが必要となり処理時間が長大化するため、200件に増加させて API コール
        回数を 1/4 に削減した。

        Args:
            record_count: 投入するレコード総数
            batch_size: 1バッチあたりのレコード数（最大500、ただしペイロードサイズ制限に注意）

        Returns:
            投入したレコード総数
        """
        if batch_size > 500:
            batch_size = 500
        log = logger.bind(database="s3vectors")
        total_inserted = 0

        for start in range(0, record_count, batch_size):
            end = min(start + batch_size, record_count)
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    count = self.ingest_batch(start, end)
                    total_inserted += count
                    break
                except Exception as e:
                    log.warning("batch_insert_retry", start=start, end=end, attempt=attempt, error=str(e))
                    if attempt == MAX_RETRIES:
                        log.error("batch_insert_failed", start=start, end=end, error=str(e))
                        break
                    time.sleep(RETRY_DELAY_SECONDS)

        log.info("ingest_all_complete", total_inserted=total_inserted)
        return total_inserted
