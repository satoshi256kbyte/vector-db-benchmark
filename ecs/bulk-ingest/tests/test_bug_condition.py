"""バグ条件探索テスト: Aurora テーブル未存在時の SQL 実行エラー.

**Property 1: Bug Condition** - Aurora テーブル未存在時に ensure_table() による
pgvector 拡張の有効化とテーブル自動作成が行われ、後続の SQL 操作が正常完了すること。

**Validates: Requirements 1.1, 1.2, 1.3**

未修正コードではこのテストは失敗する（バグの存在を証明する）。
修正後は ensure_table() が追加され、テストが成功する。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from index_manager import AuroraIndexManager, HNSW_INDEX_NAME, INDEX_NAME, VECTOR_DIMENSION
from ingestion import AuroraIngester


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

batch_start_st = st.integers(min_value=0, max_value=100)
batch_size_st = st.integers(min_value=1, max_value=10)


def _make_mock_connection(table_exists: bool = False) -> MagicMock:
    """テーブル存在/非存在をシミュレートするモック psycopg2 コネクションを生成する.

    Args:
        table_exists: True ならテーブルが既に存在する状態をシミュレート

    Returns:
        モック psycopg2 コネクション
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ===========================================================================
# Property 1.1: ensure_table() メソッドが存在し、呼び出し可能であること
# ===========================================================================


class TestEnsureTableExists:
    """ensure_table() メソッドの存在確認テスト.

    **Validates: Requirements 2.1, 2.2, 2.3**

    未修正コードでは ensure_table() が存在しないため AttributeError で失敗する。
    """

    def test_aurora_index_manager_has_ensure_table(self) -> None:
        """AuroraIndexManager に ensure_table() メソッドが存在すること."""
        mock_conn = _make_mock_connection()
        manager = AuroraIndexManager(mock_conn)
        assert hasattr(manager, "ensure_table"), (
            "AuroraIndexManager に ensure_table() メソッドが存在しない。"
            "テーブル未存在時の自動作成機能が未実装。"
        )
        assert callable(getattr(manager, "ensure_table")), "ensure_table は呼び出し可能でなければならない"


# ===========================================================================
# Property 1.2: テーブル未存在時に ensure_table() → drop_index() が正常完了
# ===========================================================================


class TestDropIndexWithMissingTable:
    """テーブル未存在時の drop_index() テスト.

    **Validates: Requirements 1.1, 2.1**

    バグ条件: target_db == "aurora" AND task_mode == "index_drop" AND NOT tableExists("embeddings")
    期待動作: ensure_table() でテーブル自動作成後、drop_index() が正常完了する。
    未修正コード: ensure_table() が存在しないため失敗する。
    """

    @given(dummy=st.integers(min_value=0, max_value=100))
    @settings(max_examples=10, deadline=None)
    def test_ensure_table_then_drop_index_succeeds(self, dummy: int) -> None:
        """ensure_table() 呼び出し後に drop_index() が例外なく完了すること.

        **Validates: Requirements 1.1**

        Args:
            dummy: Hypothesis が生成するダミー値（テーブル未存在状態の多様性を表現）
        """
        mock_conn = _make_mock_connection(table_exists=False)
        manager = AuroraIndexManager(mock_conn)

        # ensure_table() を呼び出してテーブルを自動作成
        manager.ensure_table()

        # drop_index() が例外なく完了すること
        manager.drop_index()


# ===========================================================================
# Property 1.3: テーブル未存在時に ensure_table() → ingest_batch() が正常完了
# ===========================================================================


class TestIngestBatchWithMissingTable:
    """テーブル未存在時の ingest_batch() テスト.

    **Validates: Requirements 1.2, 2.2**

    バグ条件: target_db == "aurora" AND task_mode == "ingest" AND NOT tableExists("embeddings")
    期待動作: ensure_table() でテーブル自動作成後、ingest_batch() が正常完了する。
    未修正コード: ensure_table() が存在しないため失敗する。
    """

    @given(start=batch_start_st, size=batch_size_st)
    @settings(max_examples=10, deadline=None)
    def test_ensure_table_then_ingest_batch_succeeds(self, start: int, size: int) -> None:
        """ensure_table() 呼び出し後に ingest_batch() が例外なく完了すること.

        **Validates: Requirements 1.2**

        Args:
            start: バッチ開始インデックス
            size: バッチサイズ
        """
        mock_conn = _make_mock_connection(table_exists=False)
        manager = AuroraIndexManager(mock_conn)
        ingester = AuroraIngester(mock_conn)

        # ensure_table() を呼び出してテーブルを自動作成
        manager.ensure_table()

        # ingest_batch() が例外なく完了すること
        end = start + size
        inserted = ingester.ingest_batch(start, end)
        assert inserted == size


# ===========================================================================
# Property 1.4: ensure_table() が pgvector 拡張を有効化すること
# ===========================================================================


class TestEnsureTableCreatesPgvectorExtension:
    """ensure_table() が pgvector 拡張の有効化を行うことのテスト.

    **Validates: Requirements 1.3, 2.3**

    バグ条件: pgvector 拡張未インストール時に vector 型が認識されない。
    期待動作: ensure_table() が CREATE EXTENSION IF NOT EXISTS vector を実行する。
    未修正コード: ensure_table() が存在しないため失敗する。
    """

    def test_ensure_table_executes_create_extension(self) -> None:
        """ensure_table() が CREATE EXTENSION IF NOT EXISTS vector を実行すること.

        **Validates: Requirements 1.3**
        """
        mock_conn = _make_mock_connection(table_exists=False)
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        manager = AuroraIndexManager(mock_conn)

        manager.ensure_table()

        # cursor.execute の呼び出し引数を検証
        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        extension_sql_found = False
        for sql in executed_sqls:
            if "CREATE EXTENSION" in sql and "vector" in sql:
                extension_sql_found = True
                break
        assert extension_sql_found, (
            "ensure_table() が CREATE EXTENSION IF NOT EXISTS vector を実行していない。"
            "pgvector 拡張の自動有効化が未実装。"
        )

    def test_ensure_table_executes_create_table(self) -> None:
        """ensure_table() が CREATE TABLE IF NOT EXISTS embeddings を実行すること.

        **Validates: Requirements 2.1**
        """
        mock_conn = _make_mock_connection(table_exists=False)
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        manager = AuroraIndexManager(mock_conn)

        manager.ensure_table()

        # cursor.execute の呼び出し引数を検証
        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        create_table_found = False
        for sql in executed_sqls:
            if "CREATE TABLE" in sql and INDEX_NAME in sql:
                create_table_found = True
                break
        assert create_table_found, (
            f"ensure_table() が CREATE TABLE IF NOT EXISTS {INDEX_NAME} を実行していない。"
            "テーブル自動作成が未実装。"
        )
