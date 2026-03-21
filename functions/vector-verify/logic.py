"""動作確認Lambda用ビジネスロジック.

Aurora (pgvector) および OpenSearch Serverless に対する
ベクトルデータの投入・検索処理を提供する。
"""

from __future__ import annotations

import json
import os
import random
import time

import boto3
import psycopg2
from aws_lambda_powertools import Logger, Tracer
from models import DatabaseResult
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

logger = Logger(service="vector-verify")
tracer = Tracer(service="vector-verify")

VECTOR_DIMENSION = 1536
VECTOR_COUNT = 5
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2.0
OPENSEARCH_INDEX_NAME = "embeddings"


def generate_dummy_vectors(count: int, dimension: int) -> list[list[float]]:
    """ダミーベクトルを生成する（外部API不使用）.

    Args:
        count: 生成するベクトル数
        dimension: ベクトルの次元数

    Returns:
        count 個の dimension 次元ベクトルのリスト
    """
    return [[random.uniform(-1.0, 1.0) for _ in range(dimension)] for _ in range(count)]


def _get_aurora_credentials() -> dict[str, str]:
    """Secrets Manager から Aurora 認証情報を取得する.

    Returns:
        host, port, username, password, dbname を含む辞書

    Raises:
        RuntimeError: シークレットの取得に失敗した場合
    """
    secret_arn = os.environ["AURORA_SECRET_ARN"]
    client = boto3.client("secretsmanager")
    try:
        response = client.get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        msg = f"Secrets Manager からの認証情報取得に失敗: {exc}"
        raise RuntimeError(msg) from exc
    secret: dict[str, str] = json.loads(response["SecretString"])
    return secret


def _connect_aurora(credentials: dict[str, str]) -> psycopg2.extensions.connection:
    """Aurora に接続する（リトライ付き）.

    Args:
        credentials: Secrets Manager から取得した認証情報

    Returns:
        psycopg2 コネクション

    Raises:
        RuntimeError: 最大リトライ回数を超えても接続できなかった場合
    """
    cluster_endpoint = os.environ.get("AURORA_CLUSTER_ENDPOINT", credentials.get("host", ""))
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            conn: psycopg2.extensions.connection = psycopg2.connect(
                host=cluster_endpoint,
                port=int(credentials.get("port", "5432")),
                user=credentials["username"],
                password=credentials["password"],
                dbname=credentials.get("dbname", "postgres"),
                connect_timeout=10,
            )
            logger.info("Aurora 接続成功", extra={"attempt": attempt})
            return conn
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Aurora 接続リトライ", extra={"attempt": attempt, "error": str(exc)})
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
    msg = f"Aurora 接続に {MAX_RETRIES} 回失敗: {last_error}"
    raise RuntimeError(msg)


@tracer.capture_method
def init_aurora_pgvector(conn: psycopg2.extensions.connection) -> None:
    """pgvector 拡張を有効化し、テーブルとインデックスを作成する.

    Args:
        conn: Aurora への psycopg2 コネクション
    """
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        logger.info("pgvector 拡張を有効化")

    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                embedding vector(1536) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS embeddings_hnsw_idx
                ON embeddings USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """
        )
        conn.commit()
    logger.info("テーブルとインデックスを作成")


@tracer.capture_method
def insert_aurora_vectors(conn: psycopg2.extensions.connection, vectors: list[list[float]]) -> int:
    """Aurora にベクトルデータを投入する.

    Args:
        conn: Aurora への psycopg2 コネクション
        vectors: 投入するベクトルのリスト

    Returns:
        投入件数

    Raises:
        Exception: データ投入に失敗した場合（トランザクションはロールバック済み）
    """
    try:
        with conn.cursor() as cur:
            for i, vec in enumerate(vectors):
                cur.execute(
                    "INSERT INTO embeddings (content, embedding) VALUES (%s, %s);",
                    (f"dummy-document-{i}", str(vec)),
                )
        conn.commit()
        logger.info("Aurora ベクトル投入完了", extra={"count": len(vectors)})
    except Exception:
        conn.rollback()
        logger.exception("Aurora ベクトル投入失敗")
        raise
    return len(vectors)


@tracer.capture_method
def search_aurora_vectors(conn: psycopg2.extensions.connection, query_vector: list[float], top_k: int = 3) -> int:
    """Aurora で ANN クエリを実行する.

    Args:
        conn: Aurora への psycopg2 コネクション
        query_vector: クエリベクトル
        top_k: 返却する近傍数

    Returns:
        検索結果件数
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content, embedding <=> %s::vector AS distance FROM embeddings ORDER BY distance LIMIT %s;",
            (str(query_vector), top_k),
        )
        results = cur.fetchall()
    logger.info("Aurora ANN クエリ完了", extra={"result_count": len(results)})
    return len(results)


def _get_opensearch_client() -> OpenSearch:
    """OpenSearch Serverless クライアントを生成する.

    Returns:
        OpenSearch クライアント
    """
    endpoint = os.environ["OPENSEARCH_ENDPOINT"]
    host = endpoint.replace("https://", "").rstrip("/")

    credentials = boto3.Session().get_credentials()
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "aoss",
        session_token=credentials.token,
    )

    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )
    return client


def _create_opensearch_index(client: OpenSearch) -> None:
    """OpenSearch にインデックスを作成する（存在しない場合のみ）.

    Args:
        client: OpenSearch クライアント
    """
    if client.indices.exists(index=OPENSEARCH_INDEX_NAME):
        logger.info("OpenSearch インデックスは既に存在", extra={"index": OPENSEARCH_INDEX_NAME})
        return

    index_body = {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
            }
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
            }
        },
    }
    client.indices.create(index=OPENSEARCH_INDEX_NAME, body=index_body)
    logger.info("OpenSearch インデックス作成完了", extra={"index": OPENSEARCH_INDEX_NAME})


@tracer.capture_method
def insert_opensearch_vectors(vectors: list[list[float]]) -> int:
    """OpenSearch にベクトルデータを投入する（リトライ付き）.

    Args:
        vectors: 投入するベクトルのリスト

    Returns:
        投入件数

    Raises:
        RuntimeError: 最大リトライ回数を超えても投入できなかった場合
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _get_opensearch_client()
            _create_opensearch_index(client)

            for i, vec in enumerate(vectors):
                doc = {
                    "id": i,
                    "content": f"dummy-document-{i}",
                    "embedding": vec,
                }
                client.index(index=OPENSEARCH_INDEX_NAME, body=doc, id=str(i))

            # インデックスをリフレッシュして検索可能にする
            client.indices.refresh(index=OPENSEARCH_INDEX_NAME)
            logger.info("OpenSearch ベクトル投入完了", extra={"count": len(vectors)})
            return len(vectors)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("OpenSearch 投入リトライ", extra={"attempt": attempt, "error": str(exc)})
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)

    msg = f"OpenSearch ベクトル投入に {MAX_RETRIES} 回失敗: {last_error}"
    raise RuntimeError(msg)


@tracer.capture_method
def search_opensearch_vectors(query_vector: list[float], top_k: int = 3) -> int:
    """OpenSearch で ANN クエリを実行する（リトライ付き）.

    Args:
        query_vector: クエリベクトル
        top_k: 返却する近傍数

    Returns:
        検索結果件数

    Raises:
        RuntimeError: 最大リトライ回数を超えても検索できなかった場合
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _get_opensearch_client()
            search_body = {
                "size": top_k,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": query_vector,
                            "k": top_k,
                        }
                    }
                },
            }
            response = client.search(index=OPENSEARCH_INDEX_NAME, body=search_body)
            result_count: int = len(response["hits"]["hits"])
            logger.info("OpenSearch ANN クエリ完了", extra={"result_count": result_count})
            return result_count
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("OpenSearch 検索リトライ", extra={"attempt": attempt, "error": str(exc)})
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)

    msg = f"OpenSearch 検索に {MAX_RETRIES} 回失敗: {last_error}"
    raise RuntimeError(msg)


@tracer.capture_method
def run_aurora_verify(vectors: list[list[float]], query_vector: list[float]) -> DatabaseResult:
    """Aurora (pgvector) の動作確認を実行する.

    Args:
        vectors: 投入するベクトルのリスト
        query_vector: 検索用クエリベクトル

    Returns:
        Aurora の動作確認結果
    """
    try:
        credentials = _get_aurora_credentials()
        conn = _connect_aurora(credentials)
        try:
            init_aurora_pgvector(conn)
            insert_count = insert_aurora_vectors(conn, vectors)
            search_result_count = search_aurora_vectors(conn, query_vector)
        finally:
            conn.close()

        return DatabaseResult(
            database="aurora_pgvector",
            insert_count=insert_count,
            search_result_count=search_result_count,
            success=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Aurora 動作確認失敗")
        return DatabaseResult(
            database="aurora_pgvector",
            insert_count=0,
            search_result_count=0,
            success=False,
            error_message=str(exc),
        )


@tracer.capture_method
def run_opensearch_verify(vectors: list[list[float]], query_vector: list[float]) -> DatabaseResult:
    """OpenSearch Serverless の動作確認を実行する.

    Args:
        vectors: 投入するベクトルのリスト
        query_vector: 検索用クエリベクトル

    Returns:
        OpenSearch の動作確認結果
    """
    try:
        insert_count = insert_opensearch_vectors(vectors)
        search_result_count = search_opensearch_vectors(query_vector)

        return DatabaseResult(
            database="opensearch",
            insert_count=insert_count,
            search_result_count=search_result_count,
            success=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenSearch 動作確認失敗")
        return DatabaseResult(
            database="opensearch",
            insert_count=0,
            search_result_count=0,
            success=False,
            error_message=str(exc),
        )
