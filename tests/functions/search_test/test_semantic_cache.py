"""セマンティックキャッシュ制御のユニットテスト・プロパティテスト."""

from __future__ import annotations

import importlib
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


def _import_semantic_cache() -> ModuleType:
    """functions/search-test/semantic_cache.py を外部依存モック付きでインポートする."""
    search_test_dir = str(
        Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test"
    )

    # 外部依存のモック設定
    mock_psycopg2 = MagicMock()
    mock_psycopg2_extensions = MagicMock()
    mock_powertools = MagicMock()
    mock_boto3 = MagicMock()
    mock_botocore = MagicMock()
    mock_botocore_config = MagicMock()
    mock_botocore_exceptions = MagicMock()

    ext_mocks: dict[str, MagicMock] = {
        "psycopg2": mock_psycopg2,
        "psycopg2.extensions": mock_psycopg2_extensions,
        "aws_lambda_powertools": mock_powertools,
        "boto3": mock_boto3,
        "botocore": mock_botocore,
        "botocore.config": mock_botocore_config,
        "botocore.exceptions": mock_botocore_exceptions,
    }

    # 現在の sys.path と sys.modules を保存
    original_path = sys.path[:]
    modules_to_remove = [
        "semantic_cache",
        "cache_store",
        "logic",
        "models",
        "embedding",
        "vector_generator",
    ]
    modules_to_restore: dict[str, object] = {}

    for mod_name in modules_to_remove:
        modules_to_restore[mod_name] = sys.modules.pop(mod_name, None)

    saved_ext: dict[str, object] = {}
    for mod_name, mock in ext_mocks.items():
        saved_ext[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

    try:
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)

        module = importlib.import_module("semantic_cache")
        return module
    finally:
        sys.path[:] = original_path
        for mod_name in modules_to_remove:
            sys.modules.pop(mod_name, None)
            if modules_to_restore[mod_name] is not None:
                sys.modules[mod_name] = modules_to_restore[mod_name]  # type: ignore[assignment]
        for mod_name in ext_mocks:
            if saved_ext[mod_name] is not None:
                sys.modules[mod_name] = saved_ext[mod_name]  # type: ignore[assignment]
            else:
                sys.modules.pop(mod_name, None)


_semantic_cache = _import_semantic_cache()
CacheResult = _semantic_cache.CacheResult
lookup_and_search = _semantic_cache.lookup_and_search
_find_similar_with_score = _semantic_cache._find_similar_with_score
_write_cache = _semantic_cache._write_cache
_search_aurora_results = _semantic_cache._search_aurora_results


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


class TestCacheResult:
    """CacheResult dataclass のテスト."""

    def test_cache_hit_result(self) -> None:
        """キャッシュヒット時の CacheResult を正しく生成できる."""
        result = CacheResult(
            hit=True,
            similarity_score=0.97,
            results=[{"content": "test", "distance": 0.1}],
            lookup_time_ms=5.2,
            source="cache",
        )
        assert result.hit is True
        assert result.similarity_score == 0.97
        assert result.results == [{"content": "test", "distance": 0.1}]
        assert result.lookup_time_ms == 5.2
        assert result.source == "cache"

    def test_cache_miss_result(self) -> None:
        """キャッシュミス時の CacheResult を正しく生成できる."""
        result = CacheResult(
            hit=False,
            similarity_score=None,
            results=[{"content": "test", "distance": 0.2}],
            lookup_time_ms=3.1,
            source="aurora",
        )
        assert result.hit is False
        assert result.similarity_score is None
        assert result.source == "aurora"

    def test_bypass_result(self) -> None:
        """バイパス時の CacheResult を正しく生成できる."""
        result = CacheResult(
            hit=False,
            similarity_score=None,
            results=[{"content": "test", "distance": 0.3}],
            lookup_time_ms=1.0,
            source="bypass",
        )
        assert result.hit is False
        assert result.source == "bypass"


class TestFindSimilarWithScore:
    """_find_similar_with_score 関数のテスト."""

    def test_returns_none_when_no_rows(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """結果が0件の場合 (None, None) を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None

        entry, score = _find_similar_with_score(
            mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600
        )

        assert entry is None
        assert score is None

    def test_returns_none_entry_with_score_below_threshold(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """類似度が閾値未満の場合 (None, score) を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result"}],
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.80,
        )

        entry, score = _find_similar_with_score(
            mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600
        )

        assert entry is None
        assert score == 0.80

    def test_returns_entry_with_score_above_threshold(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """類似度が閾値以上の場合 (CacheEntry, score) を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            [{"title": "result", "score": 0.95}],
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.97,
        )

        entry, score = _find_similar_with_score(
            mock_connection, sample_embedding, threshold=0.95, ttl_seconds=3600
        )

        assert entry is not None
        assert entry.id == "550e8400-e29b-41d4-a716-446655440000"
        assert entry.query_text == "東京の天気"
        assert score == 0.97


class TestLookupAndSearch:
    """lookup_and_search 関数のテスト."""

    def test_cache_hit_returns_cached_results(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュヒット時にキャッシュ結果を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cached_results = [{"content": "cached result", "distance": 0.05}]
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "東京の天気",
            cached_results,
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            0.97,
        )

        result = lookup_and_search(
            query_text="東京の天気",
            query_embedding=sample_embedding,
            connection=mock_connection,
            threshold=0.95,
            top_k=10,
        )

        assert result.hit is True
        assert result.similarity_score == 0.97
        assert result.results == cached_results
        assert result.source == "cache"
        assert result.lookup_time_ms > 0

    def test_cache_miss_searches_aurora(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュミス時に Aurora 検索を実行する."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        # キャッシュルックアップ: ミス（fetchone returns None）
        # Aurora 検索: fetchall returns results
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [("result content", 0.15)]

        result = lookup_and_search(
            query_text="新しいクエリ",
            query_embedding=sample_embedding,
            connection=mock_connection,
            threshold=0.95,
            top_k=10,
        )

        assert result.hit is False
        assert result.source == "aurora"
        assert result.results == [{"content": "result content", "distance": 0.15}]
        assert result.lookup_time_ms > 0

    def test_cache_lookup_failure_bypasses_to_aurora(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュルックアップ失敗時に Aurora にバイパスする."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        # キャッシュルックアップで例外発生、Aurora 検索は成功
        cursor.execute.side_effect = [
            Exception("Connection timeout"),
            None,
        ]
        cursor.fetchall.return_value = [("bypass result", 0.2)]

        result = lookup_and_search(
            query_text="テストクエリ",
            query_embedding=sample_embedding,
            connection=mock_connection,
            threshold=0.95,
            top_k=10,
        )

        assert result.hit is False
        assert result.source == "bypass"
        assert result.similarity_score is None
        assert result.results == [{"content": "bypass result", "distance": 0.2}]

    def test_cache_miss_triggers_async_write(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュミス時に非同期キャッシュ書き込みが開始される."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [("content", 0.1)]

        with patch.object(threading.Thread, "start") as mock_start:
            result = lookup_and_search(
                query_text="テストクエリ",
                query_embedding=sample_embedding,
                connection=mock_connection,
                threshold=0.95,
                top_k=10,
            )

            assert result.hit is False
            assert result.source == "aurora"
            mock_start.assert_called_once()

    def test_aurora_search_failure_returns_none_results(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """Aurora 検索失敗時に results=None を返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        # キャッシュルックアップ: ミス
        cursor.fetchone.return_value = None
        # Aurora 検索: 失敗
        cursor.fetchall.side_effect = Exception("Aurora connection error")

        result = lookup_and_search(
            query_text="テストクエリ",
            query_embedding=sample_embedding,
            connection=mock_connection,
            threshold=0.95,
            top_k=10,
        )

        assert result.hit is False
        assert result.source == "aurora"
        assert result.results is None

    def test_lookup_time_is_measured(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """ルックアップ時間が計測される."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [("content", 0.1)]

        result = lookup_and_search(
            query_text="テストクエリ",
            query_embedding=sample_embedding,
            connection=mock_connection,
            threshold=0.95,
            top_k=10,
        )

        assert result.lookup_time_ms >= 0

    def test_ttl_seconds_passed_to_cache_write(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """ttl_seconds がキャッシュ書き込みに渡される."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [("content", 0.1)]

        with patch.object(threading, "Thread") as mock_thread_class:
            mock_thread = MagicMock()
            mock_thread_class.return_value = mock_thread

            lookup_and_search(
                query_text="テストクエリ",
                query_embedding=sample_embedding,
                connection=mock_connection,
                threshold=0.95,
                top_k=10,
                ttl_seconds=7200,
            )

            # Thread が正しい引数で作成されたことを確認
            call_kwargs = mock_thread_class.call_args[1]
            assert call_kwargs["args"][4] == 7200  # ttl_seconds


class TestSearchAuroraResults:
    """_search_aurora_results 関数のテスト."""

    def test_returns_results_as_dicts(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """Aurora 検索結果を辞書のリストとして返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("content 1", 0.1),
            ("content 2", 0.2),
            ("content 3", 0.3),
        ]

        results = _search_aurora_results(mock_connection, sample_embedding, top_k=3)

        assert len(results) == 3
        assert results[0] == {"content": "content 1", "distance": 0.1}
        assert results[1] == {"content": "content 2", "distance": 0.2}
        assert results[2] == {"content": "content 3", "distance": 0.3}

    def test_returns_empty_list_when_no_results(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """結果が0件の場合空リストを返す."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        results = _search_aurora_results(mock_connection, sample_embedding, top_k=10)

        assert results == []

    def test_raises_on_query_failure(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """クエリ失敗時に例外を発生させる."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            _search_aurora_results(mock_connection, sample_embedding, top_k=10)


class TestWriteCache:
    """_write_cache 関数のテスト."""

    def test_write_cache_does_not_raise_on_failure(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュ書き込み失敗時に例外を発生させない."""
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = Exception("Write failed")

        # 例外が発生しないことを確認
        _write_cache(
            mock_connection,
            "テストクエリ",
            sample_embedding,
            [{"content": "test", "distance": 0.1}],
            3600,
        )

    def test_write_cache_commits_on_success(
        self, mock_connection: MagicMock, sample_embedding: list[float]
    ) -> None:
        """キャッシュ書き込み成功時にコミットされる."""
        _write_cache(
            mock_connection,
            "テストクエリ",
            sample_embedding,
            [{"content": "test", "distance": 0.1}],
            3600,
        )

        mock_connection.commit.assert_called_once()


# --- プロパティテスト: キャッシュヒットレスポンスのメタデータ完全性 ---

from hypothesis import given, settings
from hypothesis import strategies as st


class TestProperty6CacheHitResponseMetadataCompleteness:
    """Property 6: キャッシュヒットレスポンスのメタデータ完全性.

    任意のキャッシュヒットレスポンスに対して、キャッシュヒット判定結果（true）、
    類似度スコア（0.0〜1.0の浮動小数点数）、キャッシュルックアップ所要時間
    （正のミリ秒値）が全て含まれること。

    **Validates: Requirements 4.5, 7.6**
    Feature: semantic-cache, Property 6: キャッシュヒットレスポンスのメタデータ完全性
    """

    @given(
        similarity_score=st.floats(
            min_value=0.95,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_hit_contains_all_metadata(
        self, similarity_score: float
    ) -> None:
        """キャッシュヒット時にメタデータが完全に含まれること.

        - hit が True であること
        - similarity_score が 0.0〜1.0 の浮動小数点数であること
        - lookup_time_ms が正のミリ秒値であること
        - source が "cache" であること
        """
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        # モック接続を作成
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # キャッシュヒットを返すようにモックを設定
        cached_results = [{"content": "cached result", "distance": 0.05}]
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "テストクエリ",
            cached_results,
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            similarity_score,
        )

        query_embedding = [0.1] * 1024

        result = lookup_and_search(
            query_text="テストクエリ",
            query_embedding=query_embedding,
            connection=conn,
            threshold=0.95,
            top_k=10,
        )

        # キャッシュヒット判定結果が True であること
        assert result.hit is True, (
            f"Expected hit=True, got {result.hit}"
        )

        # 類似度スコアが 0.0〜1.0 の浮動小数点数であること
        assert result.similarity_score is not None, (
            "similarity_score should not be None for cache hit"
        )
        assert isinstance(result.similarity_score, float), (
            f"similarity_score should be float, got "
            f"{type(result.similarity_score)}"
        )
        assert 0.0 <= result.similarity_score <= 1.0, (
            f"similarity_score should be between 0.0 and 1.0, "
            f"got {result.similarity_score}"
        )

        # キャッシュルックアップ所要時間が正のミリ秒値であること
        assert result.lookup_time_ms > 0, (
            f"lookup_time_ms should be positive, "
            f"got {result.lookup_time_ms}"
        )

        # source が "cache" であること
        assert result.source == "cache", (
            f"Expected source='cache', got '{result.source}'"
        )



# --- プロパティテスト: 類似度閾値に基づくキャッシュヒット/ミス判定 ---


class TestProperty5SimilarityThresholdHitMiss:
    """Property 5: 類似度閾値に基づくキャッシュヒット/ミス判定.

    任意のコサイン類似度スコアと Similarity_Threshold に対して、
    スコアが閾値以上の場合はキャッシュヒット、閾値未満の場合は
    キャッシュミスと判定されること。

    **Validates: Requirements 4.2, 4.3**
    Feature: semantic-cache, Property 5: 類似度閾値に基づくキャッシュヒット/ミス判定
    """

    @given(
        similarity=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        threshold=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200, deadline=None)
    def test_hit_when_similarity_gte_threshold(
        self, similarity: float, threshold: float
    ) -> None:
        """類似度が閾値以上の場合、キャッシュヒットと判定されること."""
        # 類似度 >= 閾値のケースのみテスト
        if similarity < threshold:
            return

        # モック接続を作成
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # DB がキャッシュエントリを返す（類似度が閾値以上）
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "テストクエリ",
            [{"content": "cached result", "distance": 0.05}],
            datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            similarity,
        )

        query_embedding = [0.1] * 1024

        result = lookup_and_search(
            query_text="テストクエリ",
            query_embedding=query_embedding,
            connection=conn,
            threshold=threshold,
            top_k=10,
        )

        assert result.hit is True, (
            f"Expected cache hit for similarity={similarity}, "
            f"threshold={threshold}, but got miss"
        )
        assert result.source == "cache", (
            f"Expected source='cache' for similarity={similarity}, "
            f"threshold={threshold}, but got '{result.source}'"
        )
        assert result.similarity_score == similarity

    @given(
        similarity=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        threshold=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200, deadline=None)
    def test_miss_when_similarity_lt_threshold(
        self, similarity: float, threshold: float
    ) -> None:
        """類似度が閾値未満の場合、キャッシュミスと判定されること."""
        # 類似度 < 閾値のケースのみテスト
        if similarity >= threshold:
            return

        # モック接続を作成
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # DB がエントリを返すが類似度が閾値未満
        # _find_similar_with_score は (None, score) を返す
        cursor.fetchone.return_value = (
            "550e8400-e29b-41d4-a716-446655440000",
            "テストクエリ",
            [{"content": "cached result", "distance": 0.05}],
            datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            3600,
            similarity,
        )
        # Aurora 検索結果
        cursor.fetchall.return_value = [
            ("aurora result", 0.2),
        ]

        query_embedding = [0.1] * 1024

        with patch.object(threading.Thread, "start"):
            result = lookup_and_search(
                query_text="テストクエリ",
                query_embedding=query_embedding,
                connection=conn,
                threshold=threshold,
                top_k=10,
            )

        assert result.hit is False, (
            f"Expected cache miss for similarity={similarity}, "
            f"threshold={threshold}, but got hit"
        )
        assert result.source == "aurora", (
            f"Expected source='aurora' for similarity={similarity}, "
            f"threshold={threshold}, but got '{result.source}'"
        )

    @given(
        threshold=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_miss_when_no_cache_entries(
        self, threshold: float
    ) -> None:
        """キャッシュにエントリがない場合、キャッシュミスと判定されること."""
        # モック接続を作成
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # DB がエントリを返さない
        cursor.fetchone.return_value = None
        # Aurora 検索結果
        cursor.fetchall.return_value = [
            ("aurora result", 0.3),
        ]

        query_embedding = [0.1] * 1024

        with patch.object(threading.Thread, "start"):
            result = lookup_and_search(
                query_text="テストクエリ",
                query_embedding=query_embedding,
                connection=conn,
                threshold=threshold,
                top_k=10,
            )

        assert result.hit is False, (
            f"Expected cache miss when no entries exist, "
            f"threshold={threshold}, but got hit"
        )
        assert result.source == "aurora"


# --- プロパティテスト: キャッシュミス時のエントリ保存 ---


class TestProperty7CacheMissEntryStorage:
    """Property 7: キャッシュミス時のエントリ保存.

    任意のキャッシュミス結果に対して、Cache_Store に保存される Cache_Entry は
    元のクエリ embedding、クエリテキスト、Aurora 検索結果、現在のタイムスタンプ、
    および設定された TTL 値を正しく含むこと。

    **Validates: Requirements 5.1**
    Feature: semantic-cache, Property 7: キャッシュミス時のエントリ保存
    """

    @given(
        query_text=st.text(
            alphabet=st.characters(categories=("L", "N", "P")),
            min_size=1,
            max_size=100,
        ),
        ttl_seconds=st.integers(min_value=1, max_value=604800),
    )
    @settings(max_examples=100, deadline=None)
    def test_write_cache_receives_correct_args_on_miss(
        self,
        query_text: str,
        ttl_seconds: int,
    ) -> None:
        """キャッシュミス時に _write_cache に正しい引数が渡されること.

        lookup_and_search がキャッシュミスを検出した場合、
        threading.Thread 経由で _write_cache が呼ばれ、
        その引数に query_text, query_embedding, search_results, ttl_seconds が
        正しく含まれることを検証する。
        """
        # テスト用 embedding（1024次元）
        query_embedding = [0.5] * 1024
        aurora_results = [{"content": "result", "distance": 0.1}]

        # モック接続を作成
        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # キャッシュルックアップ: ミス（fetchone returns None）
        cursor.fetchone.return_value = None
        # Aurora 検索: 結果を返す
        cursor.fetchall.return_value = [("result", 0.1)]

        # threading.Thread をパッチして引数をキャプチャ
        with patch.object(threading, "Thread") as mock_thread_class:
            mock_thread = MagicMock()
            mock_thread_class.return_value = mock_thread

            lookup_and_search(
                query_text=query_text,
                query_embedding=query_embedding,
                connection=mock_conn,
                threshold=0.95,
                top_k=10,
                ttl_seconds=ttl_seconds,
            )

            # Thread が作成されたことを確認
            mock_thread_class.assert_called_once()
            call_kwargs = mock_thread_class.call_args[1]

            # target が _write_cache であること
            assert call_kwargs["target"] == _write_cache

            # args に正しい値が含まれること
            thread_args = call_kwargs["args"]
            assert thread_args[0] is mock_conn  # connection
            assert thread_args[1] == query_text  # query_text
            assert thread_args[2] == query_embedding  # query_embedding
            assert thread_args[3] == aurora_results  # search_results
            assert thread_args[4] == ttl_seconds  # ttl_seconds

    @given(
        query_text=st.text(
            alphabet=st.characters(categories=("L", "N", "P")),
            min_size=1,
            max_size=100,
        ),
        ttl_seconds=st.integers(min_value=1, max_value=604800),
    )
    @settings(max_examples=100, deadline=None)
    def test_write_cache_creates_entry_with_correct_fields(
        self,
        query_text: str,
        ttl_seconds: int,
    ) -> None:
        """_write_cache が正しいフィールドを持つ CacheEntry を store_entry に渡すこと.

        _write_cache を直接呼び出し、store_entry に渡される CacheEntry が
        元のクエリ embedding、クエリテキスト、検索結果、現在のタイムスタンプ、
        TTL 値を正しく含むことを検証する。
        """
        query_embedding = [0.3] * 1024
        search_results: list[dict[str, object]] = [
            {"content": "test result", "distance": 0.2}
        ]

        # モック接続を作成
        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # _write_cache を実行する前の時刻を記録
        before_call = datetime.now(tz=timezone.utc)

        _write_cache(
            mock_conn,
            query_text,
            query_embedding,
            search_results,
            ttl_seconds,
        )

        after_call = datetime.now(tz=timezone.utc)

        # store_entry が呼ばれた（= cursor.execute が呼ばれた）ことを確認
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args[0][1]

        # INSERT パラメータの検証
        # call_args: (id, embedding_str, query_text, search_results_json, created_at, ttl_seconds)
        stored_id = call_args[0]
        stored_query_text = call_args[2]
        stored_created_at = call_args[4]
        stored_ttl = call_args[5]

        # UUID 形式であること
        assert len(stored_id) == 36  # UUID format: 8-4-4-4-12

        # query_text が正しいこと
        assert stored_query_text == query_text

        # created_at が呼び出し前後の時刻の間にあること
        assert before_call <= stored_created_at <= after_call

        # ttl_seconds が正しいこと
        assert stored_ttl == ttl_seconds

        # コミットされたこと
        mock_conn.commit.assert_called_once()
