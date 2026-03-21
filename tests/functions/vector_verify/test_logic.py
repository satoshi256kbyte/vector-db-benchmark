"""ビジネスロジック (logic.py) のユニットテスト.

generate_dummy_vectors のエッジケース、
Aurora / OpenSearch / S3 Vectors 操作のモックテスト、
run_aurora_verify / run_opensearch_verify / run_s3vectors_verify の統合テストを含む。
"""

from __future__ import annotations

import importlib
import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# logic.py は psycopg2 等の外部依存を持つため、モック環境下でリロードする
# ---------------------------------------------------------------------------
def _passthrough_decorator(func=None, **kwargs):  # noqa: ANN001, ANN003
    if func is not None:
        return func
    return _passthrough_decorator


def _reload_logic():  # noqa: ANN202
    mock_powertools = MagicMock()
    mock_tracer = mock_powertools.Tracer.return_value
    mock_tracer.capture_method = _passthrough_decorator
    mock_tracer.capture_lambda_handler = _passthrough_decorator
    mock_logger = mock_powertools.Logger.return_value
    mock_logger.inject_lambda_context = _passthrough_decorator

    ext_mocks = {
        "psycopg2": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "opensearchpy": MagicMock(),
        "requests_aws4auth": MagicMock(),
        "aws_lambda_powertools": mock_powertools,
        "aws_lambda_powertools.utilities": MagicMock(),
        "aws_lambda_powertools.utilities.typing": MagicMock(),
    }
    for mod_name, mock in ext_mocks.items():
        sys.modules[mod_name] = mock
    sys.modules.pop("logic", None)
    return importlib.import_module("logic")


_logic = _reload_logic()

generate_dummy_vectors = _logic.generate_dummy_vectors
_get_aurora_credentials = _logic._get_aurora_credentials
_connect_aurora = _logic._connect_aurora
init_aurora_pgvector = _logic.init_aurora_pgvector
insert_aurora_vectors = _logic.insert_aurora_vectors
search_aurora_vectors = _logic.search_aurora_vectors
insert_opensearch_vectors = _logic.insert_opensearch_vectors
search_opensearch_vectors = _logic.search_opensearch_vectors
run_aurora_verify = _logic.run_aurora_verify
run_opensearch_verify = _logic.run_opensearch_verify
insert_s3vectors_vectors = _logic.insert_s3vectors_vectors
search_s3vectors_vectors = _logic.search_s3vectors_vectors
run_s3vectors_verify = _logic.run_s3vectors_verify
MAX_RETRIES = _logic.MAX_RETRIES

from models import DatabaseResult


# ---------------------------------------------------------------------------
# generate_dummy_vectors エッジケーステスト
# ---------------------------------------------------------------------------


class TestGenerateDummyVectors:
    """generate_dummy_vectors のエッジケーステスト."""

    def test_count_zero_returns_empty(self) -> None:
        """count=0 は空リストを返す."""
        result = generate_dummy_vectors(0, 128)
        assert result == []

    def test_dimension_one(self) -> None:
        """dimension=1 は各ベクトルが要素1つのリストを返す."""
        result = generate_dummy_vectors(3, 1)
        assert len(result) == 3
        for vec in result:
            assert len(vec) == 1

    def test_count_one(self) -> None:
        """count=1 はベクトル1つのリストを返す."""
        result = generate_dummy_vectors(1, 10)
        assert len(result) == 1
        assert len(result[0]) == 10

    def test_large_dimension(self) -> None:
        """大きな次元数 (1536) でも正しく動作する."""
        result = generate_dummy_vectors(2, 1536)
        assert len(result) == 2
        for vec in result:
            assert len(vec) == 1536

    def test_values_within_range(self) -> None:
        """すべての値が [-1.0, 1.0] の範囲内."""
        result = generate_dummy_vectors(10, 64)
        for vec in result:
            for val in vec:
                assert -1.0 <= val <= 1.0


# ---------------------------------------------------------------------------
# _get_aurora_credentials テスト
# ---------------------------------------------------------------------------


class TestGetAuroraCredentials:
    """_get_aurora_credentials のモックテスト."""

    @patch.dict("os.environ", {"AURORA_SECRET_ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:test"})
    def test_returns_parsed_secret(self) -> None:
        """Secrets Manager から認証情報を正しく取得する."""
        secret_payload = {
            "host": "aurora-host",
            "port": "5432",
            "username": "admin",
            "password": "secret",
            "dbname": "postgres",
        }
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps(secret_payload)}

        with patch.object(_logic, "boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = _get_aurora_credentials()

        mock_boto3.client.assert_called_once_with("secretsmanager")
        mock_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:test"
        )
        assert result == secret_payload

    @patch.dict("os.environ", {"AURORA_SECRET_ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:test"})
    def test_raises_on_failure(self) -> None:
        """Secrets Manager 取得失敗時に RuntimeError を送出する."""
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("access denied")

        with patch.object(_logic, "boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            with pytest.raises(RuntimeError, match="認証情報取得に失敗"):
                _get_aurora_credentials()


# ---------------------------------------------------------------------------
# _connect_aurora テスト
# ---------------------------------------------------------------------------


class TestConnectAurora:
    """_connect_aurora のリトライロジックテスト."""

    @patch.dict("os.environ", {"AURORA_CLUSTER_ENDPOINT": "aurora-endpoint"})
    def test_success_on_first_try(self) -> None:
        """初回接続成功."""
        mock_conn = MagicMock()
        with (
            patch.object(_logic, "psycopg2") as mock_psycopg2,
            patch.object(_logic.time, "sleep") as mock_sleep,
        ):
            mock_psycopg2.connect.return_value = mock_conn
            credentials = {"username": "admin", "password": "secret", "port": "5432", "dbname": "postgres"}

            conn = _connect_aurora(credentials)

            assert conn is mock_conn
            mock_psycopg2.connect.assert_called_once()
            mock_sleep.assert_not_called()

    @patch.dict("os.environ", {"AURORA_CLUSTER_ENDPOINT": "aurora-endpoint"})
    def test_success_after_retry(self) -> None:
        """1回失敗後にリトライで接続成功."""
        mock_conn = MagicMock()
        with (
            patch.object(_logic, "psycopg2") as mock_psycopg2,
            patch.object(_logic.time, "sleep"),
        ):
            mock_psycopg2.connect.side_effect = [Exception("timeout"), mock_conn]
            credentials = {"username": "admin", "password": "secret", "port": "5432", "dbname": "postgres"}

            conn = _connect_aurora(credentials)

            assert conn is mock_conn
            assert mock_psycopg2.connect.call_count == 2

    @patch.dict("os.environ", {"AURORA_CLUSTER_ENDPOINT": "aurora-endpoint"})
    def test_failure_after_max_retries(self) -> None:
        """最大リトライ回数超過で RuntimeError."""
        with (
            patch.object(_logic, "psycopg2") as mock_psycopg2,
            patch.object(_logic.time, "sleep"),
        ):
            mock_psycopg2.connect.side_effect = Exception("connection refused")
            credentials = {"username": "admin", "password": "secret", "port": "5432", "dbname": "postgres"}

            with pytest.raises(RuntimeError, match=f"{MAX_RETRIES} 回失敗"):
                _connect_aurora(credentials)

            assert mock_psycopg2.connect.call_count == MAX_RETRIES


# ---------------------------------------------------------------------------
# init_aurora_pgvector テスト
# ---------------------------------------------------------------------------


class TestInitAuroraPgvector:
    """init_aurora_pgvector のモックテスト."""

    def test_executes_ddl_statements(self) -> None:
        """pgvector 拡張有効化と DDL が実行される."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda _: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda *_: False

        init_aurora_pgvector(mock_conn)

        assert mock_conn.autocommit is not None
        assert mock_cursor.execute.call_count >= 3
        mock_conn.commit.assert_called()


# ---------------------------------------------------------------------------
# insert_aurora_vectors テスト
# ---------------------------------------------------------------------------


class TestInsertAuroraVectors:
    """insert_aurora_vectors のモックテスト."""

    def test_inserts_and_commits(self) -> None:
        """INSERT 文が各ベクトルに対して実行され commit される."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda _: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda *_: False

        vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        count = insert_aurora_vectors(mock_conn, vectors)

        assert count == 3
        assert mock_cursor.execute.call_count == 3
        mock_conn.commit.assert_called_once()

    def test_rollback_on_error(self) -> None:
        """INSERT 失敗時にロールバックされる."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("insert error")
        mock_conn.cursor.return_value.__enter__ = lambda _: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda *_: False

        with pytest.raises(Exception, match="insert error"):
            insert_aurora_vectors(mock_conn, [[0.1, 0.2]])

        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# search_aurora_vectors テスト
# ---------------------------------------------------------------------------


class TestSearchAuroraVectors:
    """search_aurora_vectors のモックテスト."""

    def test_returns_result_count(self) -> None:
        """検索結果件数を正しく返す."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "doc-0", 0.1), (2, "doc-1", 0.2)]
        mock_conn.cursor.return_value.__enter__ = lambda _: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda *_: False

        count = search_aurora_vectors(mock_conn, [0.1, 0.2], top_k=3)

        assert count == 2
        mock_cursor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# insert_opensearch_vectors テスト
# ---------------------------------------------------------------------------


class TestInsertOpensearchVectors:
    """insert_opensearch_vectors のモックテスト."""

    def test_inserts_documents(self) -> None:
        """各ベクトルがドキュメントとしてインデックスされる."""
        mock_client = MagicMock()

        with (
            patch.object(_logic, "_get_opensearch_client", return_value=mock_client),
            patch.object(_logic, "_create_opensearch_index"),
            patch.object(_logic.time, "sleep"),
        ):
            vectors = [[0.1, 0.2], [0.3, 0.4]]
            count = insert_opensearch_vectors(vectors)

        assert count == 2
        assert mock_client.index.call_count == 2
        mock_client.indices.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# search_opensearch_vectors テスト
# ---------------------------------------------------------------------------


class TestSearchOpensearchVectors:
    """search_opensearch_vectors のモックテスト."""

    def test_returns_result_count(self) -> None:
        """検索結果件数を正しく返す."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_id": "0", "_source": {"content": "doc-0"}},
                    {"_id": "1", "_source": {"content": "doc-1"}},
                ]
            }
        }

        with (
            patch.object(_logic, "_get_opensearch_client", return_value=mock_client),
            patch.object(_logic.time, "sleep"),
        ):
            count = search_opensearch_vectors([0.1, 0.2], top_k=3)

        assert count == 2
        mock_client.search.assert_called_once()


# ---------------------------------------------------------------------------
# run_aurora_verify テスト
# ---------------------------------------------------------------------------


class TestRunAuroraVerify:
    """run_aurora_verify の統合モックテスト."""

    def test_success_returns_database_result(self) -> None:
        """正常系: DatabaseResult(success=True) を返す."""
        mock_conn = MagicMock()

        with (
            patch.object(_logic, "_get_aurora_credentials", return_value={"username": "admin", "password": "secret"}),
            patch.object(_logic, "_connect_aurora", return_value=mock_conn),
            patch.object(_logic, "init_aurora_pgvector"),
            patch.object(_logic, "insert_aurora_vectors", return_value=5),
            patch.object(_logic, "search_aurora_vectors", return_value=3),
        ):
            vectors = [[0.1] * 1536] * 5
            query = [0.2] * 1536
            result = run_aurora_verify(vectors, query)

        assert isinstance(result, DatabaseResult)
        assert result.database == "aurora_pgvector"
        assert result.success is True
        assert result.insert_count == 5
        assert result.search_result_count == 3
        assert result.error_message is None
        mock_conn.close.assert_called_once()

    def test_failure_returns_error_result(self) -> None:
        """異常系: success=False と error_message を返す."""
        with patch.object(_logic, "_get_aurora_credentials", side_effect=RuntimeError("secret not found")):
            result = run_aurora_verify([[0.1]], [0.2])

        assert isinstance(result, DatabaseResult)
        assert result.success is False
        assert result.error_message is not None
        assert "secret not found" in result.error_message


# ---------------------------------------------------------------------------
# run_opensearch_verify テスト
# ---------------------------------------------------------------------------


class TestRunOpensearchVerify:
    """run_opensearch_verify の統合モックテスト."""

    def test_success_returns_database_result(self) -> None:
        """正常系: DatabaseResult(success=True) を返す."""
        with (
            patch.object(_logic, "insert_opensearch_vectors", return_value=5),
            patch.object(_logic, "search_opensearch_vectors", return_value=3),
        ):
            vectors = [[0.1] * 1536] * 5
            query = [0.2] * 1536
            result = run_opensearch_verify(vectors, query)

        assert isinstance(result, DatabaseResult)
        assert result.database == "opensearch"
        assert result.success is True
        assert result.insert_count == 5
        assert result.search_result_count == 3
        assert result.error_message is None

    def test_failure_returns_error_result(self) -> None:
        """異常系: success=False と error_message を返す."""
        with patch.object(_logic, "insert_opensearch_vectors", side_effect=RuntimeError("connection failed")):
            result = run_opensearch_verify([[0.1]], [0.2])

        assert isinstance(result, DatabaseResult)
        assert result.success is False
        assert result.error_message is not None
        assert "connection failed" in result.error_message


# ---------------------------------------------------------------------------
# insert_s3vectors_vectors テスト
# ---------------------------------------------------------------------------


class TestInsertS3vectorsVectors:
    """insert_s3vectors_vectors のモックテスト."""

    @patch.dict("os.environ", {"S3VECTORS_BUCKET_NAME": "test-bucket", "S3VECTORS_INDEX_NAME": "test-index"})
    def test_inserts_vectors(self) -> None:
        """PutVectors が正しく呼ばれ投入件数を返す."""
        mock_client = MagicMock()

        with (
            patch.object(_logic, "boto3") as mock_boto3,
            patch.object(_logic.time, "sleep"),
        ):
            mock_boto3.client.return_value = mock_client
            # モジュールレベル定数を一時的に上書き
            with (
                patch.object(_logic, "S3VECTORS_BUCKET_NAME", "test-bucket"),
                patch.object(_logic, "S3VECTORS_INDEX_NAME", "test-index"),
            ):
                vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
                count = insert_s3vectors_vectors(vectors)

        assert count == 3
        mock_boto3.client.assert_called_with("s3vectors")
        mock_client.put_vectors.assert_called_once()
        call_kwargs = mock_client.put_vectors.call_args[1]
        assert call_kwargs["vectorBucketName"] == "test-bucket"
        assert call_kwargs["indexName"] == "test-index"
        assert len(call_kwargs["vectors"]) == 3

    @patch.dict("os.environ", {"S3VECTORS_BUCKET_NAME": "test-bucket", "S3VECTORS_INDEX_NAME": "test-index"})
    def test_failure_after_max_retries(self) -> None:
        """最大リトライ回数超過で RuntimeError."""
        mock_client = MagicMock()
        mock_client.put_vectors.side_effect = Exception("service unavailable")

        with (
            patch.object(_logic, "boto3") as mock_boto3,
            patch.object(_logic.time, "sleep"),
        ):
            mock_boto3.client.return_value = mock_client
            with (
                patch.object(_logic, "S3VECTORS_BUCKET_NAME", "test-bucket"),
                patch.object(_logic, "S3VECTORS_INDEX_NAME", "test-index"),
            ):
                with pytest.raises(RuntimeError, match=f"{MAX_RETRIES} 回失敗"):
                    insert_s3vectors_vectors([[0.1, 0.2]])

        assert mock_client.put_vectors.call_count == MAX_RETRIES


# ---------------------------------------------------------------------------
# search_s3vectors_vectors テスト
# ---------------------------------------------------------------------------


class TestSearchS3vectorsVectors:
    """search_s3vectors_vectors のモックテスト."""

    @patch.dict("os.environ", {"S3VECTORS_BUCKET_NAME": "test-bucket", "S3VECTORS_INDEX_NAME": "test-index"})
    def test_returns_result_count(self) -> None:
        """検索結果件数を正しく返す."""
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {
            "vectors": [
                {"key": "dummy-document-0", "distance": 0.1},
                {"key": "dummy-document-1", "distance": 0.2},
            ]
        }

        with (
            patch.object(_logic, "boto3") as mock_boto3,
            patch.object(_logic.time, "sleep"),
        ):
            mock_boto3.client.return_value = mock_client
            with (
                patch.object(_logic, "S3VECTORS_BUCKET_NAME", "test-bucket"),
                patch.object(_logic, "S3VECTORS_INDEX_NAME", "test-index"),
            ):
                count = search_s3vectors_vectors([0.1, 0.2], top_k=3)

        assert count == 2
        mock_client.query_vectors.assert_called_once()
        call_kwargs = mock_client.query_vectors.call_args[1]
        assert call_kwargs["vectorBucketName"] == "test-bucket"
        assert call_kwargs["indexName"] == "test-index"
        assert call_kwargs["topK"] == 3

    @patch.dict("os.environ", {"S3VECTORS_BUCKET_NAME": "test-bucket", "S3VECTORS_INDEX_NAME": "test-index"})
    def test_failure_after_max_retries(self) -> None:
        """最大リトライ回数超過で RuntimeError."""
        mock_client = MagicMock()
        mock_client.query_vectors.side_effect = Exception("service unavailable")

        with (
            patch.object(_logic, "boto3") as mock_boto3,
            patch.object(_logic.time, "sleep"),
        ):
            mock_boto3.client.return_value = mock_client
            with (
                patch.object(_logic, "S3VECTORS_BUCKET_NAME", "test-bucket"),
                patch.object(_logic, "S3VECTORS_INDEX_NAME", "test-index"),
            ):
                with pytest.raises(RuntimeError, match=f"{MAX_RETRIES} 回失敗"):
                    search_s3vectors_vectors([0.1, 0.2])

        assert mock_client.query_vectors.call_count == MAX_RETRIES


# ---------------------------------------------------------------------------
# run_s3vectors_verify テスト
# ---------------------------------------------------------------------------


class TestRunS3vectorsVerify:
    """run_s3vectors_verify の統合モックテスト."""

    def test_success_returns_database_result(self) -> None:
        """正常系: DatabaseResult(success=True) を返す."""
        with (
            patch.object(_logic, "insert_s3vectors_vectors", return_value=5),
            patch.object(_logic, "search_s3vectors_vectors", return_value=3),
        ):
            vectors = [[0.1] * 1536] * 5
            query = [0.2] * 1536
            result = run_s3vectors_verify(vectors, query)

        assert isinstance(result, DatabaseResult)
        assert result.database == "s3vectors"
        assert result.success is True
        assert result.insert_count == 5
        assert result.search_result_count == 3
        assert result.error_message is None

    def test_failure_returns_error_result(self) -> None:
        """異常系: success=False と error_message を返す."""
        with patch.object(_logic, "insert_s3vectors_vectors", side_effect=RuntimeError("s3vectors api error")):
            result = run_s3vectors_verify([[0.1]], [0.2])

        assert isinstance(result, DatabaseResult)
        assert result.database == "s3vectors"
        assert result.success is False
        assert result.error_message is not None
        assert "s3vectors api error" in result.error_message
