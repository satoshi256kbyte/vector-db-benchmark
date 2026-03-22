"""main.py の統合ユニットテスト.

TARGET_DB=all の後方互換性テストと index_drop / index_create モードの動作テスト。
要件: 1.4, 4.3, 4.4
"""

from __future__ import annotations

import os
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

import main


class TestTargetDBAllBackwardCompatibility:
    """TARGET_DB=all の後方互換性テスト.

    TARGET_DB=all（または未設定）の場合、3つのDB全てを順次処理し、
    各DBでインデックス削除→データ投入→インデックス再作成を実行すること。

    Validates: Requirements 1.4
    """

    def test_target_db_all_processes_all_three_databases(self) -> None:
        """TARGET_DB=all で3つのDB全てが順次処理されること."""
        mock_aurora_conn = MagicMock()
        mock_os_client = MagicMock()
        mock_s3v_client = MagicMock()

        mock_aurora_im = MagicMock()
        mock_os_im = MagicMock()
        mock_s3v_im = MagicMock()

        mock_aurora_ing = MagicMock()
        mock_aurora_ing.ingest_all.return_value = 100
        mock_os_ing = MagicMock()
        mock_os_ing.ingest_all.return_value = 100
        mock_s3v_ing = MagicMock()
        mock_s3v_ing.ingest_all.return_value = 100

        env = {
            "TARGET_DB": "all",
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
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.S3VectorsIndexManager", return_value=mock_s3v_im),
            patch("main.AuroraIngester", return_value=mock_aurora_ing),
            patch("main.OpenSearchIngester", return_value=mock_os_ing),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ing),
        ):
            main.main()

            # 全3つの ingester の ingest_all() が呼ばれたことを検証
            mock_aurora_ing.ingest_all.assert_called_once_with(100)
            mock_os_ing.ingest_all.assert_called_once_with(100)
            mock_s3v_ing.ingest_all.assert_called_once_with(100)

            # 全3つの index_manager の drop_index() と create_index() が呼ばれたことを検証
            mock_aurora_im.drop_index.assert_called_once()
            mock_aurora_im.create_index.assert_called_once()
            mock_os_im.drop_index.assert_called_once()
            mock_os_im.create_index.assert_called_once()
            mock_s3v_im.drop_index.assert_called_once()
            mock_s3v_im.create_index.assert_called_once()

    def test_target_db_unset_defaults_to_all(self) -> None:
        """TARGET_DB 未設定時に TARGET_DB=all と同じ動作をすること."""
        mock_aurora_conn = MagicMock()
        mock_os_client = MagicMock()
        mock_s3v_client = MagicMock()

        mock_aurora_im = MagicMock()
        mock_os_im = MagicMock()
        mock_s3v_im = MagicMock()

        mock_aurora_ing = MagicMock()
        mock_aurora_ing.ingest_all.return_value = 50
        mock_os_ing = MagicMock()
        mock_os_ing.ingest_all.return_value = 50
        mock_s3v_ing = MagicMock()
        mock_s3v_ing.ingest_all.return_value = 50

        # TARGET_DB を環境変数から除外してデフォルト動作を検証
        env = {
            "TASK_MODE": "ingest",
            "RECORD_COUNT": "50",
            "S3VECTORS_BUCKET_NAME": "test-bucket",
            "S3VECTORS_INDEX_NAME": "test-index",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch.dict(os.environ, {}, clear=False),
            patch("main._get_aurora_connection", return_value=mock_aurora_conn),
            patch("main._get_opensearch_client", return_value=mock_os_client),
            patch("main._get_s3vectors_client", return_value=mock_s3v_client),
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.S3VectorsIndexManager", return_value=mock_s3v_im),
            patch("main.AuroraIngester", return_value=mock_aurora_ing),
            patch("main.OpenSearchIngester", return_value=mock_os_ing),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ing),
        ):
            # TARGET_DB 環境変数を削除してデフォルト動作を確認
            os.environ.pop("TARGET_DB", None)
            main.main()

            # 全3つの ingester が呼ばれること（= all と同じ動作）
            mock_aurora_ing.ingest_all.assert_called_once_with(50)
            mock_os_ing.ingest_all.assert_called_once_with(50)
            mock_s3v_ing.ingest_all.assert_called_once_with(50)

            # 全3つの index_manager の操作が呼ばれること
            mock_aurora_im.drop_index.assert_called_once()
            mock_aurora_im.create_index.assert_called_once()
            mock_os_im.drop_index.assert_called_once()
            mock_os_im.create_index.assert_called_once()
            mock_s3v_im.drop_index.assert_called_once()
            mock_s3v_im.create_index.assert_called_once()


class TestIndexDropMode:
    """index_drop モードの動作テスト.

    TASK_MODE=index_drop の場合、指定 DB の drop_index() のみが呼ばれ、
    データ投入や create_index() は実行されないこと。

    Validates: Requirements 4.3
    """

    def test_index_drop_opensearch_only_calls_drop_index(self) -> None:
        """TASK_MODE=index_drop, TARGET_DB=opensearch で drop_index() のみ呼ばれること."""
        mock_os_client = MagicMock()
        mock_os_im = MagicMock()

        mock_aurora_ing = MagicMock()
        mock_os_ing = MagicMock()
        mock_s3v_ing = MagicMock()

        env = {
            "TARGET_DB": "opensearch",
            "TASK_MODE": "index_drop",
            "RECORD_COUNT": "100",
            "OPENSEARCH_ENDPOINT": "https://test-endpoint",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("main._get_opensearch_client", return_value=mock_os_client),
            patch("main.OpenSearchIndexManager", return_value=mock_os_im),
            patch("main.AuroraIngester", return_value=mock_aurora_ing),
            patch("main.OpenSearchIngester", return_value=mock_os_ing),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ing),
        ):
            main.main()

            # OpenSearch の drop_index() のみが呼ばれること
            mock_os_im.drop_index.assert_called_once()

            # create_index() は呼ばれないこと
            mock_os_im.create_index.assert_not_called()

            # データ投入は一切行われないこと
            mock_aurora_ing.ingest_all.assert_not_called()
            mock_os_ing.ingest_all.assert_not_called()
            mock_s3v_ing.ingest_all.assert_not_called()


class TestIndexCreateMode:
    """index_create モードの動作テスト.

    TASK_MODE=index_create の場合、指定 DB の create_index() のみが呼ばれ、
    データ投入や drop_index() は実行されないこと。

    Validates: Requirements 4.4
    """

    def test_index_create_aurora_only_calls_create_index(self) -> None:
        """TASK_MODE=index_create, TARGET_DB=aurora で create_index() のみ呼ばれること."""
        mock_aurora_conn = MagicMock()
        mock_aurora_im = MagicMock()

        mock_aurora_ing = MagicMock()
        mock_os_ing = MagicMock()
        mock_s3v_ing = MagicMock()

        env = {
            "TARGET_DB": "aurora",
            "TASK_MODE": "index_create",
            "RECORD_COUNT": "100",
            "AURORA_SECRET_ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:test",
            "AURORA_CLUSTER_ENDPOINT": "test-endpoint",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("main._get_aurora_connection", return_value=mock_aurora_conn),
            patch("main.AuroraIndexManager", return_value=mock_aurora_im),
            patch("main.AuroraIngester", return_value=mock_aurora_ing),
            patch("main.OpenSearchIngester", return_value=mock_os_ing),
            patch("main.S3VectorsIngester", return_value=mock_s3v_ing),
        ):
            main.main()

            # Aurora の create_index() のみが呼ばれること
            mock_aurora_im.create_index.assert_called_once()

            # drop_index() は呼ばれないこと
            mock_aurora_im.drop_index.assert_not_called()

            # データ投入は一切行われないこと
            mock_aurora_ing.ingest_all.assert_not_called()
            mock_os_ing.ingest_all.assert_not_called()
            mock_s3v_ing.ingest_all.assert_not_called()


class TestInvalidTaskMode:
    """無効な TASK_MODE の拒否テスト.

    TASK_MODE に無効な値が設定された場合、sys.exit(1) で終了すること。

    Validates: Requirements 4.3, 4.4
    """

    def test_invalid_task_mode_exits_with_code_1(self) -> None:
        """無効な TASK_MODE で sys.exit(1) が呼ばれること."""
        env = {
            "TARGET_DB": "aurora",
            "TASK_MODE": "invalid_mode",
            "RECORD_COUNT": "100",
        }

        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                main.main()

            assert exc_info.value.code == 1
