"""キャッシュストア操作のユニットテスト・プロパティテスト."""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


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


# --- プロパティテスト: Cache_Entry データモデルの完全性 ---


@st.composite
def cache_entry_strategy(draw: st.DrawFn) -> CacheEntry:
    """有効な CacheEntry を生成する Hypothesis composite ストラテジー.

    1024次元の embedding は、少数のランダム値から構築することで
    Hypothesis のエントロピー制限を回避する。
    """
    entry_id = draw(st.uuids().map(str))

    # 1024次元の embedding を効率的に生成
    # 少数のランダム値を使って1024要素を構築する
    seed_values = draw(
        st.lists(
            st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=4,
            max_size=4,
        )
    )
    # 4つの値を256回ずつ繰り返して1024次元にする
    query_embedding = (seed_values * 256)[:1024]

    query_text = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N", "P")),
            min_size=1,
            max_size=100,
        )
    )
    search_results: list[dict[str, object]] = draw(
        st.lists(
            st.dictionaries(
                keys=st.text(alphabet=st.characters(categories=("L",)), min_size=1, max_size=10),
                values=st.one_of(
                    st.text(max_size=10),
                    st.integers(min_value=-100, max_value=100),
                    st.booleans(),
                ),
                min_size=1,
                max_size=3,
            ),
            min_size=1,
            max_size=3,
        )
    )
    created_at = draw(
        st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
            timezones=st.just(timezone.utc),
        )
    )
    ttl_seconds = draw(st.integers(min_value=1, max_value=604800))

    return CacheEntry(
        id=entry_id,
        query_embedding=query_embedding,
        query_text=query_text,
        search_results=search_results,
        created_at=created_at,
        ttl_seconds=ttl_seconds,
    )


class TestProperty1CacheEntryDataModelCompleteness:
    """Property 1: Cache_Entry データモデルの完全性.

    任意の有効な入力（1024次元の浮動小数点数配列、1〜1000文字のテキスト、
    JSONB形式の検索結果、UTCタイムスタンプ、正の整数TTL）に対して、
    生成された Cache_Entry は全必須フィールド（id、query_embedding、query_text、
    search_results、created_at、ttl_seconds）を正しい型で保持すること。

    **Validates: Requirements 2.1**
    Feature: semantic-cache, Property 1: Cache_Entry データモデルの完全性
    """

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_all_required_fields_present_with_correct_types(self, entry: CacheEntry) -> None:
        """全必須フィールドが正しい型で保持されること."""
        # 全必須フィールドが存在すること
        assert hasattr(entry, "id")
        assert hasattr(entry, "query_embedding")
        assert hasattr(entry, "query_text")
        assert hasattr(entry, "search_results")
        assert hasattr(entry, "created_at")
        assert hasattr(entry, "ttl_seconds")

        # 正しい型であること
        assert isinstance(entry.id, str), f"id should be str, got {type(entry.id)}"
        assert isinstance(entry.query_embedding, list), (
            f"query_embedding should be list, got {type(entry.query_embedding)}"
        )
        assert isinstance(entry.query_text, str), (
            f"query_text should be str, got {type(entry.query_text)}"
        )
        assert isinstance(entry.search_results, list), (
            f"search_results should be list, got {type(entry.search_results)}"
        )
        assert isinstance(entry.created_at, datetime), (
            f"created_at should be datetime, got {type(entry.created_at)}"
        )
        assert isinstance(entry.ttl_seconds, int), (
            f"ttl_seconds should be int, got {type(entry.ttl_seconds)}"
        )

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_embedding_dimension_is_1024(self, entry: CacheEntry) -> None:
        """query_embedding が1024次元であること."""
        assert len(entry.query_embedding) == 1024
        assert all(isinstance(v, float) for v in entry.query_embedding)

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_query_text_is_non_empty(self, entry: CacheEntry) -> None:
        """query_text が1文字以上であること."""
        assert len(entry.query_text) >= 1

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_search_results_is_list_of_dicts(self, entry: CacheEntry) -> None:
        """search_results が辞書のリストであること."""
        assert len(entry.search_results) >= 1
        for item in entry.search_results:
            assert isinstance(item, dict)

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_created_at_has_utc_timezone(self, entry: CacheEntry) -> None:
        """created_at が UTC タイムゾーンを持つこと."""
        assert entry.created_at.tzinfo is not None
        assert entry.created_at.tzinfo == timezone.utc

    @given(entry=cache_entry_strategy())
    @settings(max_examples=100, deadline=None)
    def test_ttl_seconds_is_positive(self, entry: CacheEntry) -> None:
        """ttl_seconds が正の整数であること."""
        assert entry.ttl_seconds > 0

    @given(
        entry_id=st.uuids().map(str),
        query_text=st.text(
            alphabet=st.characters(categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
        created_at=st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
            timezones=st.just(timezone.utc),
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_default_ttl_is_3600(
        self,
        entry_id: str,
        query_text: str,
        created_at: datetime,
    ) -> None:
        """ttl_seconds のデフォルト値が3600であること."""
        entry = CacheEntry(
            id=entry_id,
            query_embedding=[0.1] * 1024,
            query_text=query_text,
            search_results=[{"key": "value"}],
            created_at=created_at,
        )

        assert entry.ttl_seconds == 3600


class TestProperty3TTLCleanupThreshold:
    """Property 3: TTLクリーンアップ閾値判定.

    任意の Cache_Store 内のエントリ集合に対して、TTL超過エントリの割合が20%以下の場合は
    物理削除が実行されず、20%を超えた場合のみ超過エントリが物理削除されること。

    **Validates: Requirements 2.5**
    Feature: semantic-cache, Property 3: TTLクリーンアップ閾値判定
    """

    @given(
        total=st.integers(min_value=1, max_value=10000),
        expired_fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_no_deletion_when_expired_ratio_at_or_below_20_percent(
        self, total: int, expired_fraction: float
    ) -> None:
        """超過率が20%以下の場合、物理削除が実行されないこと."""
        expired = int(total * expired_fraction)
        # 超過率が20%以下のケースのみテスト
        if total == 0 or expired / total > 0.20:
            return

        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (total, expired)

        result = cleanup_expired(mock_conn, ttl_seconds=3600)

        assert result == 0, (
            f"Expected 0 deletions for expired_ratio={expired}/{total}="
            f"{expired / total:.4f}, but got {result}"
        )
        mock_conn.commit.assert_not_called()

    @given(
        total=st.integers(min_value=1, max_value=10000),
        expired_fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_deletion_when_expired_ratio_exceeds_20_percent(
        self, total: int, expired_fraction: float
    ) -> None:
        """超過率が20%を超えた場合、超過エントリが物理削除されること."""
        expired = int(total * expired_fraction)
        # 超過率が20%を超えるケースのみテスト
        if total == 0 or expired / total <= 0.20:
            return

        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (total, expired)
        cursor.rowcount = expired

        result = cleanup_expired(mock_conn, ttl_seconds=3600)

        assert result == expired, (
            f"Expected {expired} deletions for expired_ratio={expired}/{total}="
            f"{expired / total:.4f}, but got {result}"
        )
        mock_conn.commit.assert_called_once()

    @given(
        total=st.integers(min_value=5, max_value=10000),
    )
    @settings(max_examples=200)
    def test_boundary_at_exactly_20_percent(self, total: int) -> None:
        """超過率がちょうど20%の場合、削除が実行されないこと（境界値テスト）."""
        expired = total // 5  # floor(total * 0.20)
        # expired/total <= 0.20 を確認
        if total == 0 or expired / total > 0.20:
            return

        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (total, expired)

        result = cleanup_expired(mock_conn, ttl_seconds=3600)

        assert result == 0, (
            f"Expected 0 deletions at boundary expired_ratio={expired}/{total}="
            f"{expired / total:.4f}, but got {result}"
        )
        mock_conn.commit.assert_not_called()


class TestProperty2TtlExpiredEntryExclusion:
    """Property 2: TTL超過エントリのキャッシュヒット除外.

    任意の Cache_Entry と現在時刻に対して、created_at + ttl_seconds が
    現在時刻を超過している場合、当該エントリはキャッシュルックアップの
    結果として返されないこと。

    TTL フィルタリングは SQL WHERE 句で実行されるため、
    期限切れエントリは DB から返されない（fetchone が None を返す）。
    このプロパティテストでは、任意の期限切れ条件に対して
    find_similar が None を返すことを検証する。

    **Validates: Requirements 2.4**
    Feature: semantic-cache, Property 2: TTL超過エントリのキャッシュヒット除外
    """

    @given(
        ttl_seconds=st.integers(min_value=1, max_value=604800),
        elapsed_extra=st.integers(min_value=1, max_value=86400),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_expired_entry_not_returned_from_cache(
        self,
        ttl_seconds: int,
        elapsed_extra: int,
        threshold: float,
    ) -> None:
        """TTL超過エントリはキャッシュルックアップで返されないこと.

        SQL WHERE 句 `created_at + (ttl_seconds || ' seconds')::interval > NOW()`
        により、期限切れエントリは DB クエリ結果から除外される。
        したがって cursor.fetchone() は None を返し、
        find_similar は None を返す。
        """
        # モック接続を作成
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # DB が None を返す（SQL WHERE 句が期限切れエントリを除外）
        cursor.fetchone.return_value = None

        # 任意の embedding ベクトル
        query_embedding = [0.1] * 1024

        result = find_similar(
            conn,
            query_embedding,
            threshold=threshold,
            ttl_seconds=ttl_seconds,
        )

        # TTL超過エントリは返されない
        assert result is None

    @given(
        ttl_seconds=st.integers(min_value=1, max_value=604800),
        elapsed_extra=st.integers(min_value=1, max_value=86400),
    )
    @settings(max_examples=100, deadline=None)
    def test_sql_query_includes_ttl_filter(
        self,
        ttl_seconds: int,
        elapsed_extra: int,
    ) -> None:
        """find_similar が実行する SQL に TTL フィルタリング条件が含まれること.

        SQL WHERE 句に created_at + ttl_seconds による有効期限チェックが
        含まれていることを検証する。
        """
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None

        query_embedding = [0.1] * 1024

        find_similar(
            conn,
            query_embedding,
            threshold=0.95,
            ttl_seconds=ttl_seconds,
        )

        # SQL クエリが実行されたことを確認
        cursor.execute.assert_called_once()
        executed_sql = cursor.execute.call_args[0][0]

        # TTL フィルタリング条件が SQL に含まれていることを検証
        assert "created_at" in executed_sql
        assert "ttl_seconds" in executed_sql
        assert "NOW()" in executed_sql

    @given(
        ttl_seconds=st.integers(min_value=1, max_value=604800),
        similarity=st.floats(min_value=0.95, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_valid_entry_returned_only_when_not_expired(
        self,
        ttl_seconds: int,
        similarity: float,
    ) -> None:
        """有効期限内のエントリのみがキャッシュヒットとして返されること.

        DB が有効なエントリを返す場合（TTL 未超過）、
        類似度が閾値以上であれば CacheEntry が返される。
        これは TTL フィルタリングが正しく機能している場合の
        正常系を検証する。
        """
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # DB が有効なエントリを返す（TTL 未超過のため SQL フィルタを通過）
        entry_id = str(uuid.uuid4())
        cursor.fetchone.return_value = (
            entry_id,
            "テストクエリ",
            [{"title": "result"}],
            datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            ttl_seconds,
            similarity,
        )

        query_embedding = [0.1] * 1024

        result = find_similar(
            conn,
            query_embedding,
            threshold=0.95,
            ttl_seconds=ttl_seconds,
        )

        # 有効期限内かつ類似度が閾値以上のエントリは返される
        assert result is not None
        assert result.id == entry_id
        assert result.ttl_seconds == ttl_seconds
