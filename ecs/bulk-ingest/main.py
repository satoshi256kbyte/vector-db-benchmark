"""ECS Fargate 一括投入タスクのエントリポイント."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict

import boto3
import structlog

from index_manager import (
    AuroraIndexManager,
    OpenSearchIndexManager,
    S3VectorsIndexManager,
)
from ingestion import AuroraIngester, OpenSearchIngester, S3VectorsIngester
from metrics import (
    DatabaseIngestionResult,
    IngestionPhaseMetrics,
    IngestionReport,
    calculate_throughput,
    calculate_total_duration,
)
from vector_generator import VECTOR_DIMENSION

logger = structlog.get_logger()

MAX_CONNECTION_RETRIES = 3
CONNECTION_RETRY_DELAY_SECONDS = 2


def _get_aurora_connection() -> "psycopg2.extensions.connection":
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

    for attempt in range(1, MAX_CONNECTION_RETRIES + 1):
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
        except psycopg2.OperationalError:
            logger.warning("aurora_connection_retry", attempt=attempt)
            if attempt == MAX_CONNECTION_RETRIES:
                raise RuntimeError(f"Aurora connection failed after {MAX_CONNECTION_RETRIES} retries")
            time.sleep(CONNECTION_RETRY_DELAY_SECONDS)

    raise RuntimeError("Aurora connection failed")  # pragma: no cover


def _get_opensearch_client() -> "OpenSearch":
    """SigV4 認証付き OpenSearch クライアントを作成する.

    Returns:
        OpenSearch クライアント

    Raises:
        RuntimeError: 接続に失敗した場合
    """
    from opensearchpy import OpenSearch, RequestsHttpConnection
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

    for attempt in range(1, MAX_CONNECTION_RETRIES + 1):
        try:
            client = OpenSearch(
                hosts=[{"host": host, "port": 443}],
                http_auth=awsauth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
            )
            client.info()
            logger.info("opensearch_connection_established", attempt=attempt)
            return client
        except Exception:
            logger.warning("opensearch_connection_retry", attempt=attempt)
            if attempt == MAX_CONNECTION_RETRIES:
                raise RuntimeError(f"OpenSearch connection failed after {MAX_CONNECTION_RETRIES} retries")
            time.sleep(CONNECTION_RETRY_DELAY_SECONDS)

    raise RuntimeError("OpenSearch connection failed")  # pragma: no cover


def _get_s3vectors_client() -> boto3.client:
    """S3 Vectors の boto3 クライアントを作成する.

    Returns:
        boto3 s3vectors クライアント

    Raises:
        RuntimeError: クライアント作成に失敗した場合
    """
    for attempt in range(1, MAX_CONNECTION_RETRIES + 1):
        try:
            client = boto3.client("s3vectors")
            logger.info("s3vectors_client_created", attempt=attempt)
            return client
        except Exception:
            logger.warning("s3vectors_client_retry", attempt=attempt)
            if attempt == MAX_CONNECTION_RETRIES:
                raise RuntimeError(f"S3 Vectors client creation failed after {MAX_CONNECTION_RETRIES} retries")
            time.sleep(CONNECTION_RETRY_DELAY_SECONDS)

    raise RuntimeError("S3 Vectors client creation failed")  # pragma: no cover


def _run_database_ingestion(
    db_name: str,
    index_manager: AuroraIndexManager | OpenSearchIndexManager | S3VectorsIndexManager,
    ingester: AuroraIngester | OpenSearchIngester | S3VectorsIngester,
    record_count: int,
) -> DatabaseIngestionResult:
    """1つのDBに対してインデックス削除→データ投入→インデックス再作成を実行する.

    Args:
        db_name: データベース識別子
        index_manager: インデックス管理オブジェクト
        ingester: データ投入オブジェクト
        record_count: 投入レコード数

    Returns:
        DatabaseIngestionResult
    """
    log = logger.bind(database=db_name)
    phases: list[IngestionPhaseMetrics] = []

    try:
        # Phase 1: インデックス削除
        log.info("phase_start", phase="index_drop")
        start = time.monotonic()
        index_manager.drop_index()
        drop_duration = time.monotonic() - start
        phases.append(IngestionPhaseMetrics(phase="index_drop", duration_seconds=drop_duration, record_count=0))
        log.info("phase_complete", phase="index_drop", duration_seconds=drop_duration)

        # Phase 2: データ投入
        log.info("phase_start", phase="data_insert")
        start = time.monotonic()
        inserted = ingester.ingest_all(record_count)
        insert_duration = time.monotonic() - start
        phases.append(
            IngestionPhaseMetrics(phase="data_insert", duration_seconds=insert_duration, record_count=inserted)
        )
        log.info("phase_complete", phase="data_insert", duration_seconds=insert_duration, record_count=inserted)

        # Phase 3: インデックス再作成
        log.info("phase_start", phase="index_create")
        start = time.monotonic()
        index_manager.create_index()
        create_duration = time.monotonic() - start
        phases.append(IngestionPhaseMetrics(phase="index_create", duration_seconds=create_duration, record_count=0))
        log.info("phase_complete", phase="index_create", duration_seconds=create_duration)

        total_duration = calculate_total_duration(phases)
        throughput = calculate_throughput(record_count, total_duration) if total_duration > 0 else 0.0

        log.info(
            "database_ingestion_complete",
            total_duration_seconds=total_duration,
            throughput_records_per_sec=throughput,
        )

        return DatabaseIngestionResult(
            database=db_name,
            phases=phases,
            total_duration_seconds=total_duration,
            throughput_records_per_sec=throughput,
            record_count=record_count,
            success=True,
        )

    except Exception as exc:
        log.error("database_ingestion_failed", error=str(exc))
        total_duration = calculate_total_duration(phases) if phases else 0.0
        return DatabaseIngestionResult(
            database=db_name,
            phases=phases,
            total_duration_seconds=total_duration,
            throughput_records_per_sec=0.0,
            record_count=record_count,
            success=False,
            error_message=str(exc),
        )


def _create_failure_result(db_name: str, record_count: int, error: str) -> DatabaseIngestionResult:
    """接続失敗時の DatabaseIngestionResult を生成する.

    Args:
        db_name: データベース識別子
        record_count: 投入レコード数
        error: エラーメッセージ

    Returns:
        失敗を示す DatabaseIngestionResult
    """
    return DatabaseIngestionResult(
        database=db_name,
        phases=[],
        total_duration_seconds=0.0,
        throughput_records_per_sec=0.0,
        record_count=record_count,
        success=False,
        error_message=error,
    )


def main() -> None:
    """メインエントリポイント: 3つのDBに対して順次データ投入を実行する."""
    logger.info("bulk_ingest_start")

    record_count = int(os.environ.get("RECORD_COUNT", "100000"))
    s3vectors_bucket_name = os.environ.get("S3VECTORS_BUCKET_NAME", "")
    s3vectors_index_name = os.environ.get("S3VECTORS_INDEX_NAME", "")

    logger.info("parameters", record_count=record_count)

    # --- Aurora pgvector ---
    aurora_result: DatabaseIngestionResult
    try:
        conn = _get_aurora_connection()
        aurora_im = AuroraIndexManager(conn)
        aurora_ing = AuroraIngester(conn)
        aurora_result = _run_database_ingestion("aurora_pgvector", aurora_im, aurora_ing, record_count)
    except Exception as exc:
        logger.error("aurora_connection_failed", error=str(exc))
        aurora_result = _create_failure_result("aurora_pgvector", record_count, str(exc))

    # --- OpenSearch Serverless ---
    opensearch_result: DatabaseIngestionResult
    try:
        os_client = _get_opensearch_client()
        os_im = OpenSearchIndexManager(os_client)
        os_ing = OpenSearchIngester(os_client)
        opensearch_result = _run_database_ingestion("opensearch", os_im, os_ing, record_count)
    except Exception as exc:
        logger.error("opensearch_connection_failed", error=str(exc))
        opensearch_result = _create_failure_result("opensearch", record_count, str(exc))

    # --- Amazon S3 Vectors ---
    s3vectors_result: DatabaseIngestionResult
    try:
        s3v_client = _get_s3vectors_client()
        s3v_im = S3VectorsIndexManager()
        s3v_ing = S3VectorsIngester(s3v_client, s3vectors_bucket_name, s3vectors_index_name)
        s3vectors_result = _run_database_ingestion("s3vectors", s3v_im, s3v_ing, record_count)
    except Exception as exc:
        logger.error("s3vectors_connection_failed", error=str(exc))
        s3vectors_result = _create_failure_result("s3vectors", record_count, str(exc))

    # --- レポート出力 ---
    report = IngestionReport(
        aurora=aurora_result,
        opensearch=opensearch_result,
        s3vectors=s3vectors_result,
        record_count=record_count,
        vector_dimension=VECTOR_DIMENSION,
    )

    logger.info("bulk_ingest_complete", report=asdict(report))


if __name__ == "__main__":
    main()
