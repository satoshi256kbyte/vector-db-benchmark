"""検索ロジック・メトリクス算出モジュール."""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import boto3
from aws_lambda_powertools import Logger

from models import DatabaseSearchResult, LatencyStats, SearchTestResponse
from vector_generator import generate_query_vectors

if TYPE_CHECKING:
    import psycopg2.extensions
    from mypy_boto3_s3vectors import S3VectorsClient
    from opensearchpy import OpenSearch

logger = Logger(service="search-test")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def calculate_latency_stats(latencies_ms: list[float]) -> LatencyStats:
    """レイテンシのリストから統計値を算出する.

    Args:
        latencies_ms: レイテンシ値のリスト（ミリ秒）

    Returns:
        レイテンシ統計

    Raises:
        ValueError: latencies_ms が空の場合
    """
    if not latencies_ms:
        raise ValueError("latencies_ms must not be empty")
    arr = sorted(latencies_ms)
    n = len(arr)
    return LatencyStats(
        avg_ms=sum(arr) / n,
        p50_ms=arr[n // 2],
        p95_ms=arr[int(n * 0.95)],
        p99_ms=arr[int(n * 0.99)],
        min_ms=arr[0],
        max_ms=arr[-1],
    )


def _create_failure_result(database: str, search_count: int, top_k: int, error: str) -> DatabaseSearchResult:
    """検索失敗時の DatabaseSearchResult を生成する.

    Args:
        database: データベース識別子
        search_count: 検索回数
        top_k: 近傍返却件数
        error: エラーメッセージ

    Returns:
        失敗を示す DatabaseSearchResult
    """
    return DatabaseSearchResult(
        database=database,
        latency=LatencyStats(avg_ms=0, p50_ms=0, p95_ms=0, p99_ms=0, min_ms=0, max_ms=0),
        throughput_qps=0.0,
        search_count=search_count,
        top_k=top_k,
        success=False,
        error_message=error,
    )


def search_aurora(
    connection: psycopg2.extensions.connection,
    query_vectors: list[list[float]],
    top_k: int,
) -> DatabaseSearchResult:
    """Aurora pgvector に対してベクトル検索を実行する.

    Args:
        connection: psycopg2 コネクション
        query_vectors: クエリベクトルのリスト
        top_k: 近傍返却件数

    Returns:
        検索結果
    """
    search_count = len(query_vectors)
    latencies_ms: list[float] = []

    total_start = time.monotonic()
    for vec in query_vectors:
        start = time.monotonic()
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT content, embedding <=> %s::vector AS distance "
                    "FROM embeddings ORDER BY distance LIMIT %s;",
                    (vec, top_k),
                )
                cur.fetchall()
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies_ms.append(elapsed_ms)
        except Exception as exc:
            logger.warning("aurora_query_failed", query_index=len(latencies_ms), error=str(exc))
            connection.rollback()
    total_duration = time.monotonic() - total_start

    if not latencies_ms:
        return _create_failure_result("aurora_pgvector", search_count, top_k, "All queries failed")

    stats = calculate_latency_stats(latencies_ms)
    throughput = len(latencies_ms) / total_duration if total_duration > 0 else 0.0

    return DatabaseSearchResult(
        database="aurora_pgvector",
        latency=stats,
        throughput_qps=throughput,
        search_count=len(latencies_ms),
        top_k=top_k,
        success=True,
    )


def search_opensearch(
    client: OpenSearch,
    query_vectors: list[list[float]],
    top_k: int,
) -> DatabaseSearchResult:
    """OpenSearch Serverless に対してベクトル検索を実行する.

    Args:
        client: OpenSearch クライアント
        query_vectors: クエリベクトルのリスト
        top_k: 近傍返却件数

    Returns:
        検索結果
    """
    search_count = len(query_vectors)
    latencies_ms: list[float] = []

    total_start = time.monotonic()
    for vec in query_vectors:
        start = time.monotonic()
        try:
            client.search(
                index="embeddings",
                body={"size": top_k, "query": {"knn": {"embedding": {"vector": vec, "k": top_k}}}},
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies_ms.append(elapsed_ms)
        except Exception as exc:
            logger.warning("opensearch_query_failed", query_index=len(latencies_ms), error=str(exc))
    total_duration = time.monotonic() - total_start

    if not latencies_ms:
        return _create_failure_result("opensearch", search_count, top_k, "All queries failed")

    stats = calculate_latency_stats(latencies_ms)
    throughput = len(latencies_ms) / total_duration if total_duration > 0 else 0.0

    return DatabaseSearchResult(
        database="opensearch",
        latency=stats,
        throughput_qps=throughput,
        search_count=len(latencies_ms),
        top_k=top_k,
        success=True,
    )


def search_s3vectors(
    client: S3VectorsClient,
    bucket_name: str,
    index_name: str,
    query_vectors: list[list[float]],
    top_k: int,
) -> DatabaseSearchResult:
    """Amazon S3 Vectors に対してベクトル検索を実行する.

    Args:
        client: boto3 s3vectors クライアント
        bucket_name: S3 Vectors バケット名
        index_name: S3 Vectors インデックス名
        query_vectors: クエリベクトルのリスト
        top_k: 近傍返却件数

    Returns:
        検索結果
    """
    search_count = len(query_vectors)
    latencies_ms: list[float] = []

    total_start = time.monotonic()
    for vec in query_vectors:
        start = time.monotonic()
        try:
            client.query_vectors(
                vectorBucketName=bucket_name,
                indexName=index_name,
                queryVector={"float32": vec},
                topK=top_k,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies_ms.append(elapsed_ms)
        except Exception as exc:
            logger.warning("s3vectors_query_failed", query_index=len(latencies_ms), error=str(exc))
    total_duration = time.monotonic() - total_start

    if not latencies_ms:
        return _create_failure_result("s3vectors", search_count, top_k, "All queries failed")

    stats = calculate_latency_stats(latencies_ms)
    throughput = len(latencies_ms) / total_duration if total_duration > 0 else 0.0

    return DatabaseSearchResult(
        database="s3vectors",
        latency=stats,
        throughput_qps=throughput,
        search_count=len(latencies_ms),
        top_k=top_k,
        success=True,
    )


def build_comparison_table(
    aurora: DatabaseSearchResult,
    opensearch: DatabaseSearchResult,
    s3vectors: DatabaseSearchResult,
) -> list[dict[str, object]]:
    """3つのDB検索結果から比較表を生成する.

    Args:
        aurora: Aurora の検索結果
        opensearch: OpenSearch の検索結果
        s3vectors: S3 Vectors の検索結果

    Returns:
        比較表形式のデータ（各行が1つのメトリクス）
    """
    results = [aurora, opensearch, s3vectors]
    metrics = ["avg_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms", "throughput_qps"]
    table: list[dict[str, object]] = []

    for metric in metrics:
        row: dict[str, object] = {"metric": metric}
        for r in results:
            if metric == "throughput_qps":
                row[r.database] = round(r.throughput_qps, 2) if r.success else "N/A"
            else:
                val = getattr(r.latency, metric, None)
                row[r.database] = round(val, 3) if r.success and val is not None else "N/A"
        table.append(row)

    return table


def run_search_test(
    search_count: int,
    top_k: int,
    record_count: int,
) -> SearchTestResponse:
    """3つのDBに対して順次検索テストを実行する.

    Args:
        search_count: クエリ実行回数
        top_k: 近傍返却件数
        record_count: 投入済みレコード数（クエリベクトル生成用）

    Returns:
        SearchTestResponse
    """
    logger.info("generating_query_vectors", search_count=search_count, record_count=record_count)
    query_vectors = generate_query_vectors(record_count, search_count)

    # --- Aurora pgvector ---
    aurora_result: DatabaseSearchResult
    try:
        conn = _get_aurora_connection()
        aurora_result = search_aurora(conn, query_vectors, top_k)
        conn.close()
    except Exception as exc:
        logger.error("aurora_search_failed", error=str(exc))
        aurora_result = _create_failure_result("aurora_pgvector", search_count, top_k, str(exc))

    # --- OpenSearch Serverless ---
    opensearch_result: DatabaseSearchResult
    try:
        os_client = _get_opensearch_client()
        opensearch_result = search_opensearch(os_client, query_vectors, top_k)
    except Exception as exc:
        logger.error("opensearch_search_failed", error=str(exc))
        opensearch_result = _create_failure_result("opensearch", search_count, top_k, str(exc))

    # --- Amazon S3 Vectors ---
    s3vectors_result: DatabaseSearchResult
    try:
        s3v_client = _get_s3vectors_client()
        bucket_name = os.environ.get("S3VECTORS_BUCKET_NAME", "")
        index_name = os.environ.get("S3VECTORS_INDEX_NAME", "")
        s3vectors_result = search_s3vectors(s3v_client, bucket_name, index_name, query_vectors, top_k)
    except Exception as exc:
        logger.error("s3vectors_search_failed", error=str(exc))
        s3vectors_result = _create_failure_result("s3vectors", search_count, top_k, str(exc))

    comparison = build_comparison_table(aurora_result, opensearch_result, s3vectors_result)

    return SearchTestResponse(
        aurora=aurora_result,
        opensearch=opensearch_result,
        s3vectors=s3vectors_result,
        search_count=search_count,
        top_k=top_k,
        comparison=comparison,
    )


def _get_aurora_connection() -> psycopg2.extensions.connection:
    """Secrets Manager からクレデンシャルを取得し Aurora に接続する.

    Returns:
        psycopg2 コネクション

    Raises:
        RuntimeError: 接続に失敗した場合
    """
    import psycopg2

    secret_arn = os.environ["AURORA_SECRET_ARN"]
    cluster_endpoint = os.environ["AURORA_CLUSTER_ENDPOINT"]

    sm_client = boto3.client("secretsmanager")
    response = sm_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            conn = psycopg2.connect(
                host=cluster_endpoint,
                port=secret.get("port", 5432),
                dbname=secret.get("dbname", "postgres"),
                user=secret["username"],
                password=secret["password"],
            )
            logger.info("aurora_connection_established", attempt=attempt)
            return conn
        except psycopg2.OperationalError as exc:
            logger.warning("aurora_connection_retry", attempt=attempt, error=str(exc))
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Aurora connection failed after {MAX_RETRIES} retries: {exc}"
                ) from exc
            time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError("Aurora connection failed")  # pragma: no cover


def _get_opensearch_client() -> OpenSearch:
    """SigV4 認証付き OpenSearch クライアントを作成する.

    Returns:
        OpenSearch クライアント

    Raises:
        RuntimeError: 接続に失敗した場合
    """
    from opensearchpy import OpenSearch as OpenSearchClient
    from opensearchpy import RequestsHttpConnection
    from requests_aws4auth import AWS4Auth

    endpoint = os.environ["OPENSEARCH_ENDPOINT"]
    region = os.environ.get("AWS_REGION", "ap-northeast-1")

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials not available")

    frozen = credentials.get_frozen_credentials()
    awsauth = AWS4Auth(
        frozen.access_key,
        frozen.secret_key,
        region,
        "aoss",
        session_token=frozen.token,
    )

    host = endpoint.replace("https://", "").replace("http://", "")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = OpenSearchClient(
                hosts=[{"host": host, "port": 443}],
                http_auth=awsauth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
            )
            # OpenSearch Serverless は root / (info API) をサポートしないため、
            # サポート対象の cat.indices API で接続確認を行う
            client.cat.indices(format="json")
            logger.info("opensearch_connection_established", attempt=attempt)
            return client
        except Exception as exc:
            logger.warning("opensearch_connection_retry", attempt=attempt, error=str(exc))
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"OpenSearch connection failed after {MAX_RETRIES} retries: {exc}"
                ) from exc
            time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError("OpenSearch connection failed")  # pragma: no cover


def _get_s3vectors_client() -> S3VectorsClient:
    """S3 Vectors の boto3 クライアントを作成する.

    Returns:
        boto3 s3vectors クライアント

    Raises:
        RuntimeError: クライアント作成に失敗した場合
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client: S3VectorsClient = boto3.client("s3vectors")
            logger.info("s3vectors_client_created", attempt=attempt)
            return client
        except Exception as exc:
            logger.warning("s3vectors_client_retry", attempt=attempt, error=str(exc))
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"S3 Vectors client creation failed after {MAX_RETRIES} retries: {exc}"
                ) from exc
            time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError("S3 Vectors client creation failed")  # pragma: no cover
