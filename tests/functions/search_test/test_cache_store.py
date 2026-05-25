"""キャッシュストア操作のユニットテスト."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def _import_cache_store() -> ModuleType:
    """functions/search-test/cache_store.py を外部依存モック付きでインポートする."""
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    # 外部依存のモック設定
    mock_psycopg2 = MagicMock()
    mock_psycopg2_extensions = MagicMock()

    ext_mocks: dict[str, MagicMock] = {
        "psycopg2": mock_psycopg2,
        "psycopg2.extensions": mock_psycopg2_extensions,
    }

    # 現在の sys.path と sys.modules を保存
    original_path = sys.path[:]
    saved_cache_store = sys.modules.pop("cache_store", None)
    saved_models = sys.modules.pop("models", None)
    saved_ext: dict[str, object] = {}
    for mod_name, mock in ext_mocks.items():
        saved_ext[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

    try:
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)

        module = importlib.import_module("cache_store")
        return module
    finally:
        sys.path[:] = original_path
        sys.modules.pop("cache_store", None)
        sys.modules.pop("models", None)
        if saved_cache_store is not None:
            sys.modules["cache_store"] = saved_cache_store
        if saved_models is not None:
            sys.modules["models"] = saved_models
        for mod_name in ext_mocks:
            if saved_ext[mod_name] is not None:
                sys.modules[mod_name] = saved_ext[mod_name]  # type: ignore[assignment]
            else:
                sys.modules.pop(mod_name, None)


def _import_models() -> ModuleType:
    """functions/search-test/models.py をインポートする."""
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    original_path = sys.path[:]
    saved_models = sys.modules.pop("models", None)

    try:
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)

        module = importlib.import_module("models")
        return module
    finally:
        sys.path[:] = original_path
        sys.modules.pop("models", None)
        if saved_models is not None:
            sys.modules["models"] = saved_models


_cache_store = _import_cache_store()
_models = _import_models()

find_similar = _cache_store.find_similar
store_entry = _cache_store.store_entry
cleanup_expired = _cache_store.cleanup_expired
CacheEntry = _models.CacheEntry


@pytest.fixture
def mock_connection() -> MagicMock:
    """モック PostgreSQL 接続を返すフィクスチャ."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture
def sample_embedding() -> list[float]:
    """テスト用の1024次元 embedding ベクトル."""
    return [0.1] * 1024


@pytest.fixture
def sample_cache_entry(sample_embedding: list[float]) -> CacheEntry:
    """テスト用の CacheEntry."""
    return CacheEntry(
        id="550e8400-e29b-41d4-a716-446655440000",
        query_embedding=sample_embedding,
        query_text="東京の天気",
        search_results=[{"title": "東京の天気予報", "score": 0.95}],
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        ttl_seconds=3600,
    )


class TestFindSimilar:
    """find_similar 関数のテスト."""

    def test_returns_none_when_no_rows(self, mock_connection: MagicMock, sample_embedding: list[float]) -> None:
        """結果が0件の場合 None を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is None

    def test_returns_none_when_similarity_below_threshold(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """類似度が閾値未満の場合 None を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result"}],
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.80,
        )

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is None

    def test_returns_entry_when_similarity_meets_threshold(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """類似度が閾値以上の場合 CacheEntry を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result", "score": 0.95}],
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.97,
        )

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is not None
        assert result.id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.query_text == "東京の天気"
        assert result.search_results == [{"title": "result", "score": 0.95}]
        assert result.ttl_seconds == 3600

    def test_returns_entry_when_similarity_equals_threshold(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """類似度が閾値と等しい場合 CacheEntry を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result"}],
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.95,
        )

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is not None

    def test_handles_json_string_search_results(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """search_results が JSON 文字列の場合パースする."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            json.dumps([{"title": "result"}]),
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.97,
        )

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is not None
        assert result.search_results == [{"title": "result"}]

    def test_adds_utc_timezone_when_missing(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """created_at にタイムゾーンがない場合 UTC を付与する."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result"}],
            datetime(2024, 1, 1, 12, 0, 0),
            3600,
            0.97,
        )

        result = find_similar(mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600)

        assert result is not None
        assert result.created_at.tzinfo == timezone.utc


class TestStoreEntry:
    """store_entry 関数のテスト."""

    def test_executes_insert_query(
        self, mock_connection: MagicMock, sample_cache_entry: CacheEntry
    ) -> None:
        """INSERT クエリが実行される."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value

        store_entry(mock_connection, sample_cache_entry)

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "INSERT INTO semantic_cache" in call_args[0][0]

    def test_commits_transaction(
        self, mock_connection: MagicMock, sample_cache_entry: CacheEntry
    ) -> None:
        """トランザクションがコミットされる."""
        store_entry(mock_connection, sample_cache_entry)

        mock_connection.commit.assert_called_once()

    def test_passes_correct_parameters(
        self, mock_connection: MagicMock, sample_cache_entry: CacheEntry
    ) -> None:
        """正しいパラメータが渡される."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value

        store_entry(mock_connection, sample_cache_entry)

        call_args = cursor.execute.call_args[0][1]
        assert call_args[0] == sample_cache_entry.id
        assert call_args[2] == sample_cache_entry.query_text
        assert call_args[4] == sample_cache_entry.created_at
        assert call_args[5] == sample_cache_entry.ttl_seconds


class TestCleanupExpired:
    """cleanup_expired 関数のテスト."""

    def test_returns_zero_when_no_entries(self, mock_connection: MagicMock) -> None:
        """テーブルが空の場合 0 を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0, 0)

        result = cleanup_expired(mock_connection, ttl_seconds=3600)

        assert result == 0

    def test_returns_zero_when_expired_ratio_at_20_percent(self, mock_connection: MagicMock) -> None:
        """超過率がちょうど20%の場合は削除しない."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (100, 20)

        result = cleanup_expired(mock_connection, ttl_seconds=3600)

        assert result == 0

    def test_deletes_when_expired_ratio_exceeds_20_percent(self, mock_connection: MagicMock) -> None:
        """超過率が20%を超えた場合は削除を実行する."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (100, 21)
        cursor.rowcount = 21

        result = cleanup_expired(mock_connection, ttl_seconds=3600)

        assert result == 21
        mock_connection.commit.assert_called_once()

    def test_does_not_commit_when_below_threshold(self, mock_connection: MagicMock) -> None:
        """超過率が20%以下の場合はコミットしない."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (100, 10)

        cleanup_expired(mock_connection, ttl_seconds=3600)

        mock_connection.commit.assert_not_called()

    def test_returns_zero_when_fetchone_returns_none(self, mock_connection: MagicMock) -> None:
        """fetchone が None を返す場合 0 を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None

        result = cleanup_expired(mock_connection, ttl_seconds=3600)

        assert result == 0
