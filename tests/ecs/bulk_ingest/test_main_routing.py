"""main.py ルーティングロジックのプロパティベーステスト.

Property 1: TARGET_DB ルーティングの正確性
Property 2: 無効な TARGET_DB の拒否
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from hypothesis import given, settings
from hypothesis import strategies as st

# main.py は ecs/bulk-ingest/ にあり、pythonpath 設定済み
import main


# DB 名と main.py 内部で使われる DB 識別子のマッピング
_DB_INTERNAL_NAMES = {
    "aurora": "aurora_pgvector",
    "opensearch": "opensearch",
    "s3vectors": "s3vectors",
}

# 各 DB の接続関数パス
_CONNECTION_PATCHES = {
    "aurora": "main._get_aurora_connection",
    "opensearch": "main._get_opensearch_client",
    "s3vectors": "main._get_s3vectors_client",
}


class TestProperty1TargetDBRoutingAccuracy:
    """Property 1: TARGET_DB ルーティングの正確性.

    任意の有効な単一 DB ターゲット（aurora, opensearch, s3vectors）に対して、
    TARGET_DB にその値が設定され TASK_MODE が ingest の場合、
    ECS タスクは指定された DB のデータ投入のみを実行し、
    他の DB の処理およびインデックス操作（drop_index / create_index）は
    一切実行しないこと。

    **Validates: Requirements 1.1, 1.2, 1.3, 1.6**
    Feature: 04-benchmark-shell-script, Property 1: TARGET_DB ルーティングの正確性
    """

    @given(target_db=st.sampled_from(["aurora", "opensearch", "s3vectors"]))
    @settings(max_examples=100)
    def test_single_db_target_only_ingests_specified_db(self, target_db: str) -> None:
        """指定 DB の ingester.ingest_all() のみが呼ばれること."""
        mock_aurora_conn = MagicMock()
        mock_os_client = MagicMock()
        mock_s3v_client = MagicMock()

        mock_aurora_ingester = MagicMock()
        mock_aurora_ingester.ingest_all.return_value = 100
        mock_os_ingester = MagicMock()
        mock_os_ingester.ingest_all.return_value = 100
        mock_s3v_ingester = MagicMock()
        mock_s3v_ingester.ingest_all.return_value = 100

        mock_aurora_im = MagicMock()
        mock_os_im = MagicMock()
        mock_s3v_im = MagicMock()

        env = {
            "TARGET_DB": target_db,
            "TASK_MODE": "ingest",
            "RECORD_COUNT": "100",
            "S3VECTORS_BUCKET_NAME": "test-bucket",
            "S3VECTORS_INDEX_NAME": "test-index",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("main._get_aurora_connection", return_value=mock_aurora_conn),
            patch("main._get_opensearch_client", return_value=mock_os_client),
            patch("main._get_s3vectors_client", return_value=mock_s3v_client),
            patch("main.AuroraIngester", return_value=mock_aurora_ingester),
            patch("main.OpenSearchIngester", return_value=mock_os_ingester),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ingester),
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.S3VectorsIndexManager", return_value=mock_s3v_im),
        ):
            main.main()

            # 指定 DB の ingester.ingest_all() が呼ばれたことを検証
            ingester_map = {
                "aurora": mock_aurora_ingester,
                "opensearch": mock_os_ingester,
                "s3vectors": mock_s3v_ingester,
            }
            target_ingester = ingester_map[target_db]
            assert target_ingester.ingest_all.called, (
                f"Expected {target_db} ingester.ingest_all() to be called"
            )

            # 他の DB の ingester.ingest_all() が呼ばれていないことを検証
            for db_name, ingester in ingester_map.items():
                if db_name != target_db:
                    assert not ingester.ingest_all.called, (
                        f"{db_name} ingester.ingest_all() should NOT be called "
                        f"when TARGET_DB={target_db}"
                    )

            # インデックス操作が一切呼ばれていないことを検証
            for im_name, im_mock in [
                ("aurora", mock_aurora_im),
                ("opensearch", mock_os_im),
                ("s3vectors", mock_s3v_im),
            ]:
                assert not im_mock.drop_index.called, (
                    f"{im_name} index_manager.drop_index() should NOT be called "
                    f"when TARGET_DB={target_db}"
                )
                assert not im_mock.create_index.called, (
                    f"{im_name} index_manager.create_index() should NOT be called "
                    f"when TARGET_DB={target_db}"
                )


class TestProperty2InvalidTargetDBRejection:
    """Property 2: 無効な TARGET_DB の拒否.

    任意の文字列で、有効な TARGET_DB 値の集合（all、aurora、opensearch、s3vectors）に
    含まれないものに対して、ECS タスクはエラーログを出力し終了コード 1 で終了すること。

    **Validates: Requirements 1.5**
    Feature: 04-benchmark-shell-script, Property 2: 無効な TARGET_DB の拒否
    """

    @given(
        target_db=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        ).filter(lambda s: s.lower() not in {"all", "aurora", "opensearch", "s3vectors"})
    )
    @settings(max_examples=100)
    def test_invalid_target_db_exits_with_code_1(self, target_db: str) -> None:
        """有効な TARGET_DB 集合に含まれない文字列で sys.exit(1) が呼ばれること."""
        mock_aurora_ingester = MagicMock()
        mock_os_ingester = MagicMock()
        mock_s3v_ingester = MagicMock()
        mock_aurora_im = MagicMock()
        mock_os_im = MagicMock()
        mock_s3v_im = MagicMock()

        env = {
            "TARGET_DB": target_db,
            "TASK_MODE": "ingest",
            "RECORD_COUNT": "100",
            "S3VECTORS_BUCKET_NAME": "test-bucket",
            "S3VECTORS_INDEX_NAME": "test-index",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("main._get_aurora_connection", return_value=MagicMock()),
            patch("main._get_opensearch_client", return_value=MagicMock()),
            patch("main._get_s3vectors_client", return_value=MagicMock()),
            patch("main.AuroraIngester", return_value=mock_aurora_ingester),
            patch("main.OpenSearchIngester", return_value=mock_os_ingester),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ingester),
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.S3VectorsIndexManager", return_value=mock_s3v_im),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main.main()

            assert exc_info.value.code == 1, f"Expected exit code 1, got {exc_info.value.code}"

            # ingester の ingest_all() が一切呼ばれていないことを検証
            for db_name, ingester in [
                ("aurora", mock_aurora_ingester),
                ("opensearch", mock_os_ingester),
                ("s3vectors", mock_s3v_ingester),
            ]:
                assert not ingester.ingest_all.called, (
                    f"{db_name} ingester.ingest_all() should NOT be called for invalid TARGET_DB={target_db!r}"
                )

            # index_manager の操作が一切呼ばれていないことを検証
            for im_name, im_mock in [
                ("aurora", mock_aurora_im),
                ("opensearch", mock_os_im),
                ("s3vectors", mock_s3v_im),
            ]:
                assert not im_mock.drop_index.called, (
                    f"{im_name} index_manager.drop_index() should NOT be called for invalid TARGET_DB={target_db!r}"
                )
                assert not im_mock.create_index.called, (
                    f"{im_name} index_manager.create_index() should NOT be called for invalid TARGET_DB={target_db!r}"
                )


class TestProperty7TaskModeRoutingAccuracy:
    """Property 7: TASK_MODE ルーティングの正確性.

    任意の有効な TASK_MODE 値（index_drop、index_create）と有効な TARGET_DB に対して、
    ECS タスクは対応するインデックス操作のみを実行し、データ投入は一切実行しないこと。

    **Validates: Requirements 4.3, 4.4**
    Feature: 04-benchmark-shell-script, Property 7: TASK_MODE ルーティングの正確性
    """

    @given(
        task_mode=st.sampled_from(["index_drop", "index_create"]),
        target_db=st.sampled_from(["aurora", "opensearch", "s3vectors"]),
    )
    @settings(max_examples=100)
    def test_task_mode_executes_only_corresponding_index_operation(
        self, task_mode: str, target_db: str
    ) -> None:
        """TASK_MODE に対応するインデックス操作のみが実行され、データ投入は行われないこと."""
        mock_aurora_conn = MagicMock()
        mock_os_client = MagicMock()

        mock_aurora_ingester = MagicMock()
        mock_os_ingester = MagicMock()
        mock_s3v_ingester = MagicMock()

        mock_aurora_im = MagicMock()
        mock_os_im = MagicMock()
        mock_s3v_im = MagicMock()

        env = {
            "TARGET_DB": target_db,
            "TASK_MODE": task_mode,
            "RECORD_COUNT": "100",
            "S3VECTORS_BUCKET_NAME": "test-bucket",
            "S3VECTORS_INDEX_NAME": "test-index",
        }

        im_map: dict[str, MagicMock] = {
            "aurora": mock_aurora_im,
            "opensearch": mock_os_im,
            "s3vectors": mock_s3v_im,
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("main._get_aurora_connection", return_value=mock_aurora_conn),
            patch("main._get_opensearch_client", return_value=mock_os_client),
            patch("main.AuroraIngester", return_value=mock_aurora_ingester),
            patch("main.OpenSearchIngester", return_value=mock_os_ingester),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ingester),
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.S3VectorsIndexManager", return_value=mock_s3v_im),
        ):
            main.main()

            # 対象 DB の index_manager で正しい操作が呼ばれたことを検証
            target_im = im_map[target_db]
            if task_mode == "index_drop":
                assert target_im.drop_index.called, (
                    f"Expected {target_db} index_manager.drop_index() to be called "
                    f"when TASK_MODE={task_mode}"
                )
                assert not target_im.create_index.called, (
                    f"{target_db} index_manager.create_index() should NOT be called "
                    f"when TASK_MODE={task_mode}"
                )
            else:
                assert target_im.create_index.called, (
                    f"Expected {target_db} index_manager.create_index() to be called "
                    f"when TASK_MODE={task_mode}"
                )
                assert not target_im.drop_index.called, (
                    f"{target_db} index_manager.drop_index() should NOT be called "
                    f"when TASK_MODE={task_mode}"
                )

            # 他の DB の index_manager は一切呼ばれていないことを検証
            for db_name, im_mock in im_map.items():
                if db_name != target_db:
                    assert not im_mock.drop_index.called, (
                        f"{db_name} index_manager.drop_index() should NOT be called "
                        f"when TARGET_DB={target_db}, TASK_MODE={task_mode}"
                    )
                    assert not im_mock.create_index.called, (
                        f"{db_name} index_manager.create_index() should NOT be called "
                        f"when TARGET_DB={target_db}, TASK_MODE={task_mode}"
                    )

            # データ投入（ingest_all）が一切呼ばれていないことを検証
            for db_name, ingester in [
                ("aurora", mock_aurora_ingester),
                ("opensearch", mock_os_ingester),
                ("s3vectors", mock_s3v_ingester),
            ]:
                assert not ingester.ingest_all.called, (
                    f"{db_name} ingester.ingest_all() should NOT be called "
                    f"when TASK_MODE={task_mode}"
                )
