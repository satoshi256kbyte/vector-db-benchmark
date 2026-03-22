"""インデックス管理ロジックのユニットテスト.

AuroraIndexManager, OpenSearchIndexManager, S3VectorsIndexManager の
インデックス削除・再作成、順序検証を行う。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

from index_manager import (
    HNSW_INDEX_NAME,
    INDEX_NAME,
    VECTOR_DIMENSION,
    AuroraIndexManager,
    OpenSearchIndexManager,
    S3VectorsIndexManager,
)


# ---------------------------------------------------------------------------
# AuroraIndexManager Tests
# ---------------------------------------------------------------------------


class TestAuroraIndexManagerDropIndex:
    """AuroraIndexManager.drop_index のテスト."""

    def test_drop_index_executes_drop_and_truncate(self) -> None:
        """DROP INDEX と TRUNCATE SQL が実行されること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manager = AuroraIndexManager(mock_conn)
        manager.drop_index()

        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 2
        assert f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME};" in calls[0][0][0]
        assert f"TRUNCATE TABLE {INDEX_NAME};" in calls[1][0][0]

    def test_drop_index_commits_transaction(self) -> None:
        """drop_index 後に commit が呼ばれること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manager = AuroraIndexManager(mock_conn)
        manager.drop_index()

        mock_conn.commit.assert_called_once()


class TestAuroraIndexManagerCreateIndex:
    """AuroraIndexManager.create_index のテスト."""

    def test_create_index_executes_create_index(self) -> None:
        """CREATE INDEX SQL が HNSW パラメータ付きで実行されること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manager = AuroraIndexManager(mock_conn)
        manager.create_index()

        mock_cursor.execute.assert_called_once()
        executed_sql: str = mock_cursor.execute.call_args[0][0]
        assert f"CREATE INDEX {HNSW_INDEX_NAME}" in executed_sql
        assert f"ON {INDEX_NAME}" in executed_sql
        assert "hnsw" in executed_sql
        assert "vector_cosine_ops" in executed_sql
        assert "m = 16" in executed_sql
        assert "ef_construction = 64" in executed_sql

    def test_create_index_commits_transaction(self) -> None:
        """create_index 後に commit が呼ばれること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manager = AuroraIndexManager(mock_conn)
        manager.create_index()

        mock_conn.commit.assert_called_once()

    def test_drop_then_create_order(self) -> None:
        """drop_index → create_index の順序で SQL が実行されること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manager = AuroraIndexManager(mock_conn)
        manager.drop_index()
        manager.create_index()

        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 3
        assert "DROP INDEX" in calls[0][0][0]
        assert "TRUNCATE" in calls[1][0][0]
        assert "CREATE INDEX" in calls[2][0][0]


# ---------------------------------------------------------------------------
# OpenSearchIndexManager Tests
# ---------------------------------------------------------------------------


class TestOpenSearchIndexManagerDropIndex:
    """OpenSearchIndexManager.drop_index のテスト."""

    def test_drop_index_is_noop(self) -> None:
        """drop_index が no-op であること（クライアントメソッドを呼ばない）."""
        mock_client = MagicMock()

        manager = OpenSearchIndexManager(mock_client)
        manager.drop_index()

        mock_client.indices.delete.assert_not_called()

    def test_drop_index_does_not_raise(self) -> None:
        """drop_index が例外を発生させないこと."""
        mock_client = MagicMock()

        manager = OpenSearchIndexManager(mock_client)
        # 例外が発生しないことを確認
        manager.drop_index()


class TestOpenSearchIndexManagerCreateIndex:
    """OpenSearchIndexManager.create_index のテスト."""

    def test_create_index_is_noop(self) -> None:
        """create_index が no-op であること（クライアントメソッドを呼ばない）."""
        mock_client = MagicMock()

        manager = OpenSearchIndexManager(mock_client)
        manager.create_index()

        mock_client.indices.create.assert_not_called()

    def test_create_index_does_not_raise(self) -> None:
        """create_index が例外を発生させないこと."""
        mock_client = MagicMock()

        manager = OpenSearchIndexManager(mock_client)
        # 例外が発生しないことを確認
        manager.create_index()


# ---------------------------------------------------------------------------
# S3VectorsIndexManager Tests
# ---------------------------------------------------------------------------


class TestS3VectorsIndexManager:
    """S3VectorsIndexManager のテスト."""

    def test_drop_index_is_noop(self) -> None:
        """drop_index が外部呼び出しを行わないこと（ログのみ）."""
        manager = S3VectorsIndexManager()
        # 例外が発生しないことを確認
        manager.drop_index()

    def test_create_index_is_noop(self) -> None:
        """create_index が外部呼び出しを行わないこと（ログのみ）."""
        manager = S3VectorsIndexManager()
        # 例外が発生しないことを確認
        manager.create_index()


# ---------------------------------------------------------------------------
# Order Verification
# ---------------------------------------------------------------------------


class TestAuroraDropCreateOrder:
    """Aurora のインデックス削除→再作成の順序検証."""

    def test_aurora_drop_create_order(self) -> None:
        """mock call tracking で DROP → TRUNCATE → CREATE の順序を検証する."""
        call_log: list[str] = []
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        def track_execute(sql: str, *args: object) -> None:
            if "DROP INDEX" in sql:
                call_log.append("drop_index")
            elif "TRUNCATE" in sql:
                call_log.append("truncate")
            elif "CREATE INDEX" in sql:
                call_log.append("create_index")

        mock_cursor.execute.side_effect = track_execute

        manager = AuroraIndexManager(mock_conn)
        manager.drop_index()
        manager.create_index()

        assert call_log == ["drop_index", "truncate", "create_index"]
