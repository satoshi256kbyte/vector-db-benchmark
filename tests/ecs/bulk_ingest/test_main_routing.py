"""main.py ルーティングロジックのプロパティベーステスト.

Property 1: TARGET_DB ルーティングの正確性
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

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
