"""保全プロパティテスト: 既存 Aurora 動作と他 DB 動作の維持.

**Property 3: Preservation** - 既存 Aurora 動作の維持
**Property 4: Preservation** - 既存エラーハンドリングと他 DB 動作の維持

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

未修正コードでこのテストは成功する（保全すべきベースライン動作を確認）。
修正後もこのテストが成功し続けることで、リグレッションがないことを保証する。
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from index_manager import AuroraIndexManager, HNSW_INDEX_NAME, INDEX_NAME
from ingestion import AuroraIngester


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

batch_start_st = st.integers(min_value=0, max_value=50)
batch_size_st = st.integers(min_value=1, max_value=10)


def _make_mock_connection() -> MagicMock:
    """テーブルが存在する状態をシミュレートするモック psycopg2 コネクションを生成する.

    Returns:
        モック psycopg2 コネクション（cursor コンテキストマネージャ対応）
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ===========================================================================
# Property 3.1: テーブル存在時の drop_index() が HNSW 削除 + TRUNCATE を実行
# ===========================================================================


class TestDropIndexPreservation:
    """テーブル存在時の drop_index() 動作保全テスト.

    **Validates: Requirements 3.1**

    embeddings テーブルが既に存在する場合、drop_index() は従来通り
    HNSW インデックスの削除とテーブルの TRUNCATE を正常に実行する。
    """

    @given(dummy=st.integers(min_value=0, max_value=100))
    @settings(max_examples=10, deadline=None)
    def test_drop_index_executes_drop_and_truncate(self, dummy: int) -> None:
        """drop_index() が DROP INDEX と TRUNCATE TABLE を実行すること.

        **Validates: Requirements 3.1**

        Args:
            dummy: Hypothesis が生成するダミー値（テスト多様性のため）
        """
        mock_conn = _make_mock_connection()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        manager = AuroraIndexManager(mock_conn)

        manager.drop_index()

        # cursor.execute の呼び出し引数を検証
        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]

        # DROP INDEX IF EXISTS が実行されること
        drop_found = False
        for sql in executed_sqls:
            if "DROP INDEX" in sql and HNSW_INDEX_NAME in sql:
                drop_found = True
                break
        assert drop_found, f"drop_index() が DROP INDEX IF EXISTS {HNSW_INDEX_NAME} を実行していない"

        # TRUNCATE TABLE が実行されること
        truncate_found = False
        for sql in executed_sqls:
            if "TRUNCATE" in sql and INDEX_NAME in sql:
                truncate_found = True
                break
        assert truncate_found, f"drop_index() が TRUNCATE TABLE {INDEX_NAME} を実行していない"

        # commit が呼ばれること
        mock_conn.commit.assert_called()

    def test_drop_index_sql_order(self) -> None:
        """drop_index() が DROP INDEX → TRUNCATE の順序で実行すること.

        **Validates: Requirements 3.1**
        """
        mock_conn = _make_mock_connection()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        manager = AuroraIndexManager(mock_conn)

        manager.drop_index()

        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert len(executed_sqls) == 2, f"drop_index() は2つの SQL を実行すべき（実際: {len(executed_sqls)}）"
        assert "DROP INDEX" in executed_sqls[0], "最初の SQL は DROP INDEX であるべき"
        assert "TRUNCATE" in executed_sqls[1], "2番目の SQL は TRUNCATE であるべき"


# ===========================================================================
# Property 3.2: テーブル存在時の ingest_batch() が INSERT を実行
# ===========================================================================


class TestIngestBatchPreservation:
    """テーブル存在時の ingest_batch() 動作保全テスト.

    **Validates: Requirements 3.2**

    embeddings テーブルが既に存在する場合、ingest_batch() は従来通り
    INSERT INTO embeddings でデータ投入を正常に実行する。
    """

    @given(start=batch_start_st, size=batch_size_st)
    @settings(max_examples=15, deadline=None)
    def test_ingest_batch_executes_insert(self, start: int, size: int) -> None:
        """ingest_batch() が INSERT INTO embeddings を実行し、正しいレコード数を返すこと.

        **Validates: Requirements 3.2**

        Args:
            start: バッチ開始インデックス
            size: バッチサイズ
        """
        mock_conn = _make_mock_connection()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        ingester = AuroraIngester(mock_conn)

        end = start + size
        inserted = ingester.ingest_batch(start, end)

        # 戻り値がバッチサイズと一致すること
        assert inserted == size, f"ingest_batch() の戻り値が不正: expected={size}, actual={inserted}"

        # INSERT INTO embeddings が実行されること
        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert len(executed_sqls) == 1, "ingest_batch() は1つの SQL を実行すべき"
        assert "INSERT INTO embeddings" in executed_sqls[0], "SQL に INSERT INTO embeddings が含まれるべき"

        # commit が呼ばれること
        mock_conn.commit.assert_called()

    @given(start=batch_start_st, size=batch_size_st)
    @settings(max_examples=10, deadline=None)
    def test_ingest_batch_generates_correct_params(self, start: int, size: int) -> None:
        """ingest_batch() が正しい数のパラメータを生成すること.

        **Validates: Requirements 3.2**

        Args:
            start: バッチ開始インデックス
            size: バッチサイズ
        """
        mock_conn = _make_mock_connection()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        ingester = AuroraIngester(mock_conn)

        end = start + size
        ingester.ingest_batch(start, end)

        # execute に渡されたパラメータを検証
        call_args = mock_cursor.execute.call_args
        params = call_args.args[1]  # 2番目の引数がパラメータリスト
        # 各レコードに content と embedding の2パラメータ
        expected_param_count = size * 2
        assert len(params) == expected_param_count, (
            f"パラメータ数が不正: expected={expected_param_count}, actual={len(params)}"
        )


# ===========================================================================
# Property 3.4: create_index() が HNSW インデックスを正常作成
# ===========================================================================


class TestCreateIndexPreservation:
    """create_index() の HNSW インデックス作成動作保全テスト.

    **Validates: Requirements 3.4**

    AuroraIndexManager.create_index() は従来通り HNSW インデックスを正常に作成する。
    """

    @given(dummy=st.integers(min_value=0, max_value=100))
    @settings(max_examples=10, deadline=None)
    def test_create_index_executes_create_hnsw(self, dummy: int) -> None:
        """create_index() が CREATE INDEX で HNSW インデックスを作成すること.

        **Validates: Requirements 3.4**

        Args:
            dummy: Hypothesis が生成するダミー値（テスト多様性のため）
        """
        mock_conn = _make_mock_connection()
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        manager = AuroraIndexManager(mock_conn)

        manager.create_index()

        # cursor.execute の呼び出し引数を検証
        executed_sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert len(executed_sqls) == 1, "create_index() は1つの SQL を実行すべき"

        sql = executed_sqls[0]
        assert "CREATE INDEX" in sql, "SQL に CREATE INDEX が含まれるべき"
        assert HNSW_INDEX_NAME in sql, f"SQL に {HNSW_INDEX_NAME} が含まれるべき"
        assert "hnsw" in sql.lower(), "SQL に hnsw が含まれるべき"
        assert "vector_cosine_ops" in sql, "SQL に vector_cosine_ops が含まれるべき"

        # commit が呼ばれること
        mock_conn.commit.assert_called()


# ===========================================================================
# Property 4: _run_count_operation() のテーブル未存在ハンドリング保全
# ===========================================================================


class TestCountOperationPreservation:
    """_run_count_operation() の既存エラーハンドリング保全テスト.

    **Validates: Requirements 3.3**

    TASK_MODE=count かつ TARGET_DB=aurora で ECS タスクを実行する場合、
    _run_count_operation() の既存のテーブル未存在ハンドリング
    （does not exist → count=0）は変更されず、従来通り動作する。
    """

    @given(dummy=st.integers(min_value=0, max_value=100))
    @settings(max_examples=10, deadline=None)
    def test_count_operation_handles_table_not_exist(self, dummy: int) -> None:
        """テーブル未存在時に count=0 を出力すること.

        **Validates: Requirements 3.3**

        Args:
            dummy: Hypothesis が生成するダミー値（テスト多様性のため）
        """
        from main import _run_count_operation

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # テーブル未存在エラーをシミュレート
        mock_cursor.execute.side_effect = Exception('relation "embeddings" does not exist')

        captured_output = StringIO()

        with (
            patch("main._get_aurora_connection", return_value=mock_conn),
            patch("sys.stdout", captured_output),
        ):
            _run_count_operation("aurora")

        output = captured_output.getvalue()
        assert "RECORD_COUNT_RESULT:0" in output, (
            f"テーブル未存在時に RECORD_COUNT_RESULT:0 が出力されるべき（実際: {output!r}）"
        )

    def test_count_operation_returns_count_when_table_exists(self) -> None:
        """テーブル存在時に正しい count を出力すること.

        **Validates: Requirements 3.3**
        """
        from main import _run_count_operation

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # テーブル存在時: fetchone が (42,) を返す
        mock_cursor.fetchone.return_value = (42,)

        captured_output = StringIO()

        with (
            patch("main._get_aurora_connection", return_value=mock_conn),
            patch("sys.stdout", captured_output),
        ):
            _run_count_operation("aurora")

        output = captured_output.getvalue()
        assert "RECORD_COUNT_RESULT:42" in output, (
            f"テーブル存在時に RECORD_COUNT_RESULT:42 が出力されるべき（実際: {output!r}）"
        )
