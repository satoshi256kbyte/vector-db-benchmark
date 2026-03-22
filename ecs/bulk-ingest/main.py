"""ECS Fargate 一括投入タスクのエントリポイント."""

from __future__ import annotations

import json
import os
import sys
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
OPENSEARCH_MAX_RETRIES = 6
OPENSEARCH_RETRY_DELAY_SECONDS = 5


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

    for attempt in range(1, OPENSEARCH_MAX_RETRIES + 1):
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
            if attempt == OPENSEARCH_MAX_RETRIES:
                raise RuntimeError(f"OpenSearch connection failed after {OPENSEARCH_MAX_RETRIES} retries")
            time.sleep(OPENSEARCH_RETRY_DELAY_SECONDS)

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


VALID_TARGET_DBS = {"all", "aurora", "opensearch", "s3vectors"}
VALID_TASK_MODES = {"ingest", "index_drop", "index_create", "count"}


def _run_data_ingestion_only(
    db_name: str,
    ingester: AuroraIngester | OpenSearchIngester | S3VectorsIngester,
    record_count: int,
) -> DatabaseIngestionResult:
    """1つのDBに対してデータ投入のみを実行する（インデックス操作なし）.

    単一 DB 指定モード（TARGET_DB が aurora/opensearch/s3vectors）で使用する。
    シェルスクリプト側でインデックス操作を制御するため、ここではデータ投入のみ行う。

    Args:
        db_name: データベース識別子
        ingester: データ投入オブジェクト
        record_count: 投入レコード数

    Returns:
        DatabaseIngestionResult
    """
    log = logger.bind(database=db_name)
    phases: list[IngestionPhaseMetrics] = []

    try:
        log.info("phase_start", phase="data_insert")
        start = time.monotonic()
        inserted = ingester.ingest_all(record_count)
        insert_duration = time.monotonic() - start
        phases.append(
            IngestionPhaseMetrics(phase="data_insert", duration_seconds=insert_duration, record_count=inserted)
        )
        log.info("phase_complete", phase="data_insert", duration_seconds=insert_duration, record_count=inserted)

        total_duration = calculate_total_duration(phases)
        throughput = calculate_throughput(record_count, total_duration) if total_duration > 0 else 0.0

        log.info(
            "data_ingestion_only_complete",
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
        log.error("data_ingestion_only_failed", error=str(exc))
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


def _run_index_operation(target_db: str, operation: str) -> None:
    """指定 DB に対してインデックス操作のみを実行する.

    TASK_MODE が index_drop または index_create の場合に呼び出される。
    シェルスクリプトから ECS タスク経由でインデックス操作を実行するために使用する。

    Args:
        target_db: 対象 DB 識別子（"aurora", "opensearch", "s3vectors"）
        operation: 操作種別（"drop" または "create"）
    """
    log = logger.bind(target_db=target_db, operation=operation)
    log.info("index_operation_start")

    if target_db == "aurora":
        try:
            conn = _get_aurora_connection()
            index_manager = AuroraIndexManager(conn)
            index_manager.ensure_table()
        except Exception as exc:
            log.error("aurora_connection_failed", error=str(exc))
            sys.exit(1)
    elif target_db == "opensearch":
        try:
            os_client = _get_opensearch_client()
            index_manager = OpenSearchIndexManager(os_client)
        except Exception as exc:
            log.error("opensearch_connection_failed", error=str(exc))
            sys.exit(1)
    elif target_db == "s3vectors":
        index_manager = S3VectorsIndexManager()
    else:
        log.error("invalid_target_db_for_index_operation", target_db=target_db)
        sys.exit(1)

    try:
        if operation == "drop":
            index_manager.drop_index()
        else:
            index_manager.create_index()
        log.info("index_operation_complete")
    except Exception as exc:
        log.error("index_operation_failed", error=str(exc))
        sys.exit(1)


def _run_count_operation(target_db: str) -> None:
    """指定 DB のレコード数を取得し、構造化ログで出力する.

    TASK_MODE が count の場合に呼び出される。
    シェルスクリプトから ECS タスク経由でレコード数を取得するために使用する。
    結果は RECORD_COUNT_RESULT: {"database": ..., "count": ...} 形式で stdout に出力する。

    Args:
        target_db: 対象 DB 識別子（"aurora", "opensearch", "s3vectors"）
    """
    log = logger.bind(target_db=target_db)
    log.info("count_operation_start")

    count = 0

    if target_db == "aurora":
        try:
            conn = _get_aurora_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM embeddings;")
                result = cur.fetchone()
                count = result[0] if result else 0
            conn.close()
        except Exception as exc:
            error_str = str(exc)
            if "does not exist" in error_str:
                log.info("aurora_table_not_found", message="embeddings テーブル未作成のため count=0")
                count = 0
            else:
                log.error("aurora_count_failed", error=error_str)
                sys.exit(1)
    elif target_db == "opensearch":
        try:
            os_client = _get_opensearch_client()
            resp = os_client.count(index="embeddings")
            count = resp.get("count", 0)
        except Exception as exc:
            error_str = str(exc)
            if "index_not_found_exception" in error_str or "404" in error_str:
                log.info("opensearch_index_not_found", message="embeddings インデックス未作成のため count=0")
                count = 0
            else:
                log.error("opensearch_count_failed", error=error_str)
                sys.exit(1)
    elif target_db == "s3vectors":
        try:
            s3v_client = _get_s3vectors_client()
            bucket_name = os.environ.get("S3VECTORS_BUCKET_NAME", "")
            index_name = os.environ.get("S3VECTORS_INDEX_NAME", "")
            resp = s3v_client.list_vectors(
                vectorBucketName=bucket_name,
                indexName=index_name,
            )
            count = len(resp.get("vectors", []))
        except Exception as exc:
            error_str = str(exc)
            if "NoSuchIndex" in error_str or "NoSuchVectorBucket" in error_str or "404" in error_str:
                log.info("s3vectors_index_not_found", message="S3 Vectors インデックス未作成のため count=0")
                count = 0
            else:
                log.error("s3vectors_count_failed", error=error_str)
                sys.exit(1)
    else:
        log.error("invalid_target_db_for_count", target_db=target_db)
        sys.exit(1)

    # シェルスクリプトがパースできる形式で出力
    print(f"RECORD_COUNT_RESULT:{count}")
    log.info("count_operation_complete", database=target_db, count=count)


def _run_single_database(target_db: str, record_count: int) -> None:
    """単一 DB に対してデータ投入のみを実行する.

    インデックス操作はスキップし、データ投入フェーズのみ実行する。
    シェルスクリプト側でインデックス操作を制御する前提。

    Args:
        target_db: 対象 DB 識別子（"aurora", "opensearch", "s3vectors"）
        record_count: 投入レコード数
    """
    s3vectors_bucket_name = os.environ.get("S3VECTORS_BUCKET_NAME", "")
    s3vectors_index_name = os.environ.get("S3VECTORS_INDEX_NAME", "")

    logger.info("single_db_mode", target_db=target_db, record_count=record_count)

    result: DatabaseIngestionResult

    if target_db == "aurora":
        try:
            conn = _get_aurora_connection()
            aurora_im = AuroraIndexManager(conn)
            aurora_im.ensure_table()
            ingester = AuroraIngester(conn)
            result = _run_data_ingestion_only("aurora_pgvector", ingester, record_count)
        except Exception as exc:
            logger.error("aurora_connection_failed", error=str(exc))
            result = _create_failure_result("aurora_pgvector", record_count, str(exc))

    elif target_db == "opensearch":
        try:
            os_client = _get_opensearch_client()
            ingester = OpenSearchIngester(os_client)
            result = _run_data_ingestion_only("opensearch", ingester, record_count)
        except Exception as exc:
            logger.error("opensearch_connection_failed", error=str(exc))
            result = _create_failure_result("opensearch", record_count, str(exc))

    elif target_db == "s3vectors":
        try:
            s3v_client = _get_s3vectors_client()
            ingester = S3VectorsIngester(s3v_client, s3vectors_bucket_name, s3vectors_index_name)
            result = _run_data_ingestion_only("s3vectors", ingester, record_count)
        except Exception as exc:
            logger.error("s3vectors_connection_failed", error=str(exc))
            result = _create_failure_result("s3vectors", record_count, str(exc))

    logger.info("single_db_complete", result=asdict(result))

    if not result.success:
        sys.exit(1)


def _run_all_databases(record_count: int) -> None:
    """3つのDBに対して順次データ投入を実行する（既存動作、後方互換性維持）.

    インデックス削除→データ投入→インデックス再作成の全フェーズを実行する。

    Args:
        record_count: 投入レコード数
    """
    s3vectors_bucket_name = os.environ.get("S3VECTORS_BUCKET_NAME", "")
    s3vectors_index_name = os.environ.get("S3VECTORS_INDEX_NAME", "")

    # --- Aurora pgvector ---
    aurora_result: DatabaseIngestionResult
    try:
        conn = _get_aurora_connection()
        aurora_im = AuroraIndexManager(conn)
        aurora_im.ensure_table()
        aurora_ing = AuroraIngester(conn)
        aurora_result = _run_database_ingestion("aurora_pgvector", aurora_im, aurora_ing, record_count)
    except Exception as exc:
        logger.error("aurora_connection_failed", error=str(exc))
        aurora_result = _create_failure_result("aurora_pgvector", record_count, str(exc))

    # --- OpenSearch Serverless ---
    # OpenSearch Serverless ではインデックス削除→再作成の効果がないため、
    # データ投入のみ実行する（Bulk API で既存インデックスに直接挿入）
    opensearch_result: DatabaseIngestionResult
    try:
        os_client = _get_opensearch_client()
        os_ing = OpenSearchIngester(os_client)
        opensearch_result = _run_data_ingestion_only("opensearch", os_ing, record_count)
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


def main() -> None:
    """メインエントリポイント: TARGET_DB / TASK_MODE に応じて処理を実行する.

    環境変数 TARGET_DB の値に応じて処理対象 DB を切り替える:
    - "all" または未設定: 3つのDB全てを順次処理（インデックス操作含む、後方互換性維持）
    - "aurora" / "opensearch" / "s3vectors": 指定DBのデータ投入のみ（インデックス操作なし）
    - その他: エラーログ出力 + sys.exit(1)

    環境変数 TASK_MODE の値に応じて実行モードを切り替える:
    - "ingest" または未設定: データ投入モード（デフォルト）
    - "index_drop": インデックス削除のみ実行
    - "index_create": インデックス作成のみ実行
    - その他: エラーログ出力 + sys.exit(1)
    """
    logger.info("bulk_ingest_start")

    target_db = os.environ.get("TARGET_DB", "all").lower()
    task_mode = os.environ.get("TASK_MODE", "ingest").lower()
    record_count = int(os.environ.get("RECORD_COUNT", "100000"))

    logger.info("parameters", target_db=target_db, task_mode=task_mode, record_count=record_count)

    if target_db not in VALID_TARGET_DBS:
        logger.error("invalid_target_db", target_db=target_db)
        sys.exit(1)

    if task_mode not in VALID_TASK_MODES:
        logger.error("invalid_task_mode", task_mode=task_mode)
        sys.exit(1)

    if task_mode == "index_drop":
        _run_index_operation(target_db, "drop")
        return

    if task_mode == "index_create":
        _run_index_operation(target_db, "create")
        return

    if task_mode == "count":
        _run_count_operation(target_db)
        return

    # task_mode == "ingest"
    if target_db == "all":
        _run_all_databases(record_count)
    else:
        _run_single_database(target_db, record_count)


if __name__ == "__main__":
    main()
