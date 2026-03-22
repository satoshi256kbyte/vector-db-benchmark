"""バッチ投入ロジックのユニットテスト.

AuroraIngester, OpenSearchIngester, S3VectorsIngester の
バッチ投入、リトライ、エラーハンドリングを検証する。
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, call, patch

import pytest
from ingestion import AuroraIngester, OpenSearchIngester, S3VectorsIngester
from vector_generator import generate_vector


# ---------------------------------------------------------------------------
# AuroraIngester Tests
# ---------------------------------------------------------------------------


class TestAuroraIngesterIngestBatch:
    """AuroraIngester.ingest_batch のテスト."""

    def test_ingest_batch_executes_insert(self) -> None:
        """SQL INSERT が正しいパラメータで実行されること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        ingester = AuroraIngester(mock_conn)
        count = ingester.ingest_batch(0, 3)

        assert count == 3
        mock_cursor.execute.assert_called_once()

        executed_sql: str = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO embeddings" in executed_sql
        assert executed_sql.count("(%s, %s::vector)") == 3

        params: list[str | list[float]] = mock_cursor.execute.call_args[0][1]
        assert params[0] == "doc-0"
        assert params[1] == generate_vector(seed=0)
        assert params[2] == "doc-1"
        assert params[3] == generate_vector(seed=1)
        assert params[4] == "doc-2"
        assert params[5] == generate_vector(seed=2)

        mock_conn.commit.assert_called_once()


class TestAuroraIngesterIngestAll:
    """AuroraIngester.ingest_all のテスト."""

    def test_ingest_all_calls_correct_number_of_batches(self) -> None:
        """バッチ数が ceil(record_count / batch_size) と一致すること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        ingester = AuroraIngester(mock_conn)

        record_count = 250
        batch_size = 100
        result = ingester.ingest_all(record_count, batch_size)

        expected_batches = math.ceil(record_count / batch_size)
        assert mock_cursor.execute.call_count == expected_batches
        assert result == record_count

    @patch("ingestion.time.sleep")
    def test_ingest_all_retries_on_failure(self, mock_sleep: MagicMock) -> None:
        """バッチ失敗時にリトライ（最大3回）が実行されること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.execute.side_effect = [
            Exception("DB error"),
            Exception("DB error"),
            None,  # 3回目で成功
        ]

        ingester = AuroraIngester(mock_conn)
        result = ingester.ingest_all(10, 10)

        assert result == 10
        assert mock_cursor.execute.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(2), call(2)])

    @patch("ingestion.time.sleep")
    def test_ingest_all_continues_after_max_retries(self, mock_sleep: MagicMock) -> None:
        """最大リトライ後も例外を投げず、部分的な件数を返すこと."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.execute.side_effect = [
            Exception("DB error"),  # batch 0-100: attempt 1
            Exception("DB error"),  # batch 0-100: attempt 2
            Exception("DB error"),  # batch 0-100: attempt 3 → give up
            None,                   # batch 100-200: success
        ]

        ingester = AuroraIngester(mock_conn)
        result = ingester.ingest_all(200, 100)

        # 最初のバッチは失敗、2番目は成功
        assert result == 100
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# OpenSearchIngester Tests
# ---------------------------------------------------------------------------


class TestOpenSearchIngesterIngestBatch:
    """OpenSearchIngester.ingest_batch のテスト."""

    def test_ingest_batch_calls_bulk_api(self) -> None:
        """bulk() が正しいボディで呼び出されること."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        ingester = OpenSearchIngester(mock_client)
        count = ingester.ingest_batch(0, 2)

        assert count == 2
        mock_client.bulk.assert_called_once()

        bulk_body: list[dict[str, object]] = mock_client.bulk.call_args[1]["body"]
        # 2レコード × 2エントリ（action + document）= 4
        assert len(bulk_body) == 4
        assert bulk_body[0] == {"index": {"_index": "embeddings"}}
        assert bulk_body[1]["content"] == "doc-0"
        assert bulk_body[1]["embedding"] == generate_vector(seed=0)
        assert bulk_body[2] == {"index": {"_index": "embeddings"}}
        assert bulk_body[3]["content"] == "doc-1"
        assert bulk_body[3]["embedding"] == generate_vector(seed=1)

    def test_ingest_batch_raises_on_bulk_errors(self) -> None:
        """レスポンスにエラーがある場合 RuntimeError が発生すること."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {
            "errors": True,
            "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}],
        }

        ingester = OpenSearchIngester(mock_client)
        with pytest.raises(RuntimeError, match="OpenSearch bulk API returned errors"):
            ingester.ingest_batch(0, 1)


class TestOpenSearchIngesterIngestAll:
    """OpenSearchIngester.ingest_all のテスト."""

    @patch("ingestion.time.sleep")
    def test_ingest_all_retries_on_failure(self, mock_sleep: MagicMock) -> None:
        """バッチ失敗時にリトライが実行されること."""
        mock_client = MagicMock()
        mock_client.bulk.side_effect = [
            Exception("Connection error"),
            {"errors": False, "items": []},  # 2回目で成功
        ]

        ingester = OpenSearchIngester(mock_client)
        result = ingester.ingest_all(10, 10)

        assert result == 10
        assert mock_client.bulk.call_count == 2
        mock_sleep.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# S3VectorsIngester Tests
# ---------------------------------------------------------------------------


class TestS3VectorsIngesterIngestBatch:
    """S3VectorsIngester.ingest_batch のテスト."""

    def test_ingest_batch_calls_put_vectors(self) -> None:
        """put_vectors() が正しいパラメータで呼び出されること."""
        mock_client = MagicMock()

        ingester = S3VectorsIngester(mock_client, "test-bucket", "test-index")
        count = ingester.ingest_batch(0, 2)

        assert count == 2
        mock_client.put_vectors.assert_called_once()

        kwargs = mock_client.put_vectors.call_args[1]
        assert kwargs["vectorBucketName"] == "test-bucket"
        assert kwargs["indexName"] == "test-index"

        vectors: list[dict[str, object]] = kwargs["vectors"]
        assert len(vectors) == 2
        assert vectors[0]["key"] == "0"
        assert vectors[0]["data"] == {"float32": generate_vector(seed=0)}
        assert vectors[0]["metadata"] == {"content": "doc-0"}
        assert vectors[1]["key"] == "1"
        assert vectors[1]["data"] == {"float32": generate_vector(seed=1)}
        assert vectors[1]["metadata"] == {"content": "doc-1"}


class TestS3VectorsIngesterIngestAll:
    """S3VectorsIngester.ingest_all のテスト."""

    @patch("ingestion.time.sleep")
    def test_ingest_all_retries_on_failure(self, mock_sleep: MagicMock) -> None:
        """バッチ失敗時にリトライが実行されること."""
        mock_client = MagicMock()
        mock_client.put_vectors.side_effect = [
            Exception("API error"),
            Exception("API error"),
            None,  # 3回目で成功
        ]

        ingester = S3VectorsIngester(mock_client, "test-bucket", "test-index")
        result = ingester.ingest_all(10, 10)

        assert result == 10
        assert mock_client.put_vectors.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(2), call(2)])


# ---------------------------------------------------------------------------
# Property 2: バッチ投入の呼び出し回数 (Hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st


def _stub_vector(seed: int) -> list[float]:
    """テスト用の軽量ベクトル生成スタブ（1536次元の生成コストを回避）."""
    return [float(seed)]


class TestProperty2BatchInvocationCount:
    """Property 2: バッチ投入の呼び出し回数.

    任意の正の整数 record_count と正の整数 batch_size に対して、
    バッチ投入関数が発行するバッチ API 呼び出し回数は
    ceil(record_count / batch_size) に等しいこと。

    Feature: 03-vector-benchmark-execution, Property 2: バッチ投入の呼び出し回数

    **Validates: Requirements 4.4, 4.5, 4.6**
    """

    @given(
        record_count=st.integers(min_value=1, max_value=5000),
        batch_size=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=200, deadline=None)
    @patch("ingestion.generate_vector", side_effect=_stub_vector)
    @patch("ingestion.time.sleep")
    def test_aurora_batch_call_count(
        self, mock_sleep: MagicMock, mock_gen: MagicMock, record_count: int, batch_size: int
    ) -> None:
        """AuroraIngester の cursor.execute 呼び出し回数が ceil(record_count / batch_size) と一致すること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        ingester = AuroraIngester(mock_conn)
        ingester.ingest_all(record_count, batch_size)

        expected_calls = math.ceil(record_count / batch_size)
        assert mock_cursor.execute.call_count == expected_calls

    @given(
        record_count=st.integers(min_value=1, max_value=5000),
        batch_size=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=200, deadline=None)
    @patch("ingestion.generate_vector", side_effect=_stub_vector)
    @patch("ingestion.time.sleep")
    def test_opensearch_batch_call_count(
        self, mock_sleep: MagicMock, mock_gen: MagicMock, record_count: int, batch_size: int
    ) -> None:
        """OpenSearchIngester の client.bulk 呼び出し回数が ceil(record_count / batch_size) と一致すること."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        ingester = OpenSearchIngester(mock_client)
        ingester.ingest_all(record_count, batch_size)

        expected_calls = math.ceil(record_count / batch_size)
        assert mock_client.bulk.call_count == expected_calls

    @given(
        record_count=st.integers(min_value=1, max_value=5000),
        batch_size=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=200, deadline=None)
    @patch("ingestion.generate_vector", side_effect=_stub_vector)
    @patch("ingestion.time.sleep")
    def test_s3vectors_batch_call_count(
        self, mock_sleep: MagicMock, mock_gen: MagicMock, record_count: int, batch_size: int
    ) -> None:
        """S3VectorsIngester の client.put_vectors 呼び出し回数が ceil(record_count / effective_batch_size) と一致すること."""
        mock_client = MagicMock()

        ingester = S3VectorsIngester(mock_client, "test-bucket", "test-index")
        ingester.ingest_all(record_count, batch_size)

        # S3 Vectors PutVectors API は1回あたり最大500件のため、batch_size は500に制限される
        effective_batch_size = min(batch_size, 500)
        expected_calls = math.ceil(record_count / effective_batch_size)
        assert mock_client.put_vectors.call_count == expected_calls
