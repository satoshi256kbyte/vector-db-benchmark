"""メトリクス計測モジュールのテスト."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis import given, settings
from hypothesis import strategies as st


def _import_metrics() -> ModuleType:
    """functions/search-test/metrics.py を外部依存モック付きでインポートする."""
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    # 外部依存のモック設定
    mock_powertools = MagicMock()
    mock_logger_instance = MagicMock()
    mock_powertools.Logger.return_value = mock_logger_instance

    ext_mocks: dict[str, MagicMock] = {
        "aws_lambda_powertools": mock_powertools,
    }

    # 現在の sys.path と sys.modules を保存
    original_path = sys.path[:]
    saved_metrics = sys.modules.pop("metrics", None)
    saved_models = sys.modules.pop("models", None)
    saved_ext: dict[str, object] = {}
    for mod_name, mock in ext_mocks.items():
        saved_ext[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

    try:
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)

        # models を先にインポートして sys.modules に登録（metrics が from models import CacheStats するため）
        models_module = importlib.import_module("models")
        sys.modules["models"] = models_module

        module = importlib.import_module("metrics")
        return module
    finally:
        sys.path[:] = original_path
        sys.modules.pop("metrics", None)
        sys.modules.pop("models", None)
        if saved_metrics is not None:
            sys.modules["metrics"] = saved_metrics
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


_metrics_mod = _import_metrics()
_models_mod = _import_models()

SearchMetrics = _metrics_mod.SearchMetrics
calculate_cache_stats = _metrics_mod.calculate_cache_stats
log_search_metrics = _metrics_mod.log_search_metrics
log_cache_stats = _metrics_mod.log_cache_stats
CacheStats = _models_mod.CacheStats


class TestSearchMetrics:
    """SearchMetrics dataclass のテスト."""

    def test_all_fields_populated(self) -> None:
        """全フィールドが正しく設定されること."""
        metrics = SearchMetrics(
            total_time_ms=100.0,
            embedding_time_ms=20.0,
            lookup_time_ms=5.0,
            search_time_ms=70.0,
            cache_write_time_ms=5.0,
            cache_hit=False,
            similarity_score=0.85,
        )
        assert metrics.total_time_ms == 100.0
        assert metrics.embedding_time_ms == 20.0
        assert metrics.lookup_time_ms == 5.0
        assert metrics.search_time_ms == 70.0
        assert metrics.cache_write_time_ms == 5.0
        assert metrics.cache_hit is False
        assert metrics.similarity_score == 0.85

    def test_nullable_fields(self) -> None:
        """計測失敗時にNoneが設定できること."""
        metrics = SearchMetrics(
            total_time_ms=50.0,
            embedding_time_ms=None,
            lookup_time_ms=None,
            search_time_ms=None,
            cache_write_time_ms=None,
            cache_hit=True,
            similarity_score=None,
        )
        assert metrics.embedding_time_ms is None
        assert metrics.lookup_time_ms is None
        assert metrics.search_time_ms is None
        assert metrics.cache_write_time_ms is None
        assert metrics.similarity_score is None

    def test_to_dict(self) -> None:
        """辞書変換が正しく動作すること."""
        metrics = SearchMetrics(
            total_time_ms=100.0,
            embedding_time_ms=20.0,
            lookup_time_ms=5.0,
            search_time_ms=70.0,
            cache_write_time_ms=5.0,
            cache_hit=False,
            similarity_score=0.85,
        )
        result = metrics.to_dict()
        assert result["total_time_ms"] == 100.0
        assert result["cache_hit"] is False


class TestCalculateCacheStats:
    """calculate_cache_stats のテスト."""

    def test_empty_list(self) -> None:
        """空リストの場合はゼロ値を返すこと."""
        stats = calculate_cache_stats([])
        assert stats.total_requests == 0
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.hit_rate_percent == 0.0
        assert stats.avg_hit_latency_ms == 0.0
        assert stats.avg_miss_latency_ms == 0.0
        assert stats.latency_reduction_percent == 0.0

    def test_all_hits(self) -> None:
        """全てキャッシュヒットの場合."""
        metrics_list = [
            SearchMetrics(
                total_time_ms=10.0,
                embedding_time_ms=5.0,
                lookup_time_ms=5.0,
                search_time_ms=None,
                cache_write_time_ms=None,
                cache_hit=True,
                similarity_score=0.98,
            )
            for _ in range(5)
        ]
        stats = calculate_cache_stats(metrics_list)
        assert stats.total_requests == 5
        assert stats.cache_hits == 5
        assert stats.cache_misses == 0
        assert stats.hit_rate_percent == 100.0
        assert stats.avg_hit_latency_ms == 10.0
        assert stats.avg_miss_latency_ms == 0.0
        # No misses, so latency_reduction_percent = 0.0
        assert stats.latency_reduction_percent == 0.0

    def test_all_misses(self) -> None:
        """全てキャッシュミスの場合."""
        metrics_list = [
            SearchMetrics(
                total_time_ms=100.0,
                embedding_time_ms=20.0,
                lookup_time_ms=5.0,
                search_time_ms=70.0,
                cache_write_time_ms=5.0,
                cache_hit=False,
                similarity_score=0.5,
            )
            for _ in range(5)
        ]
        stats = calculate_cache_stats(metrics_list)
        assert stats.total_requests == 5
        assert stats.cache_hits == 0
        assert stats.cache_misses == 5
        assert stats.hit_rate_percent == 0.0
        assert stats.avg_hit_latency_ms == 0.0
        assert stats.avg_miss_latency_ms == 100.0
        # No hits, so latency_reduction_percent = 0.0
        assert stats.latency_reduction_percent == 0.0

    def test_mixed_hits_and_misses(self) -> None:
        """ヒットとミスが混在する場合の統計算出."""
        hit_metrics = [
            SearchMetrics(
                total_time_ms=10.0,
                embedding_time_ms=5.0,
                lookup_time_ms=5.0,
                search_time_ms=None,
                cache_write_time_ms=None,
                cache_hit=True,
                similarity_score=0.98,
            )
            for _ in range(3)
        ]
        miss_metrics = [
            SearchMetrics(
                total_time_ms=100.0,
                embedding_time_ms=20.0,
                lookup_time_ms=5.0,
                search_time_ms=70.0,
                cache_write_time_ms=5.0,
                cache_hit=False,
                similarity_score=0.5,
            )
            for _ in range(7)
        ]
        metrics_list = hit_metrics + miss_metrics
        stats = calculate_cache_stats(metrics_list)

        assert stats.total_requests == 10
        assert stats.cache_hits == 3
        assert stats.cache_misses == 7
        assert stats.hit_rate_percent == pytest.approx(30.0)
        assert stats.avg_hit_latency_ms == pytest.approx(10.0)
        assert stats.avg_miss_latency_ms == pytest.approx(100.0)
        # latency_reduction_percent = (1 - 10/100) * 100 = 90.0
        assert stats.latency_reduction_percent == pytest.approx(90.0)

    def test_returns_cache_stats_type(self) -> None:
        """CacheStats 型が返されること."""
        metrics_list = [
            SearchMetrics(
                total_time_ms=50.0,
                embedding_time_ms=10.0,
                lookup_time_ms=5.0,
                search_time_ms=30.0,
                cache_write_time_ms=5.0,
                cache_hit=False,
                similarity_score=0.7,
            )
        ]
        stats = calculate_cache_stats(metrics_list)
        assert type(stats).__name__ == "CacheStats"
        assert hasattr(stats, "total_requests")
        assert hasattr(stats, "cache_hits")
        assert hasattr(stats, "cache_misses")
        assert hasattr(stats, "hit_rate_percent")
        assert hasattr(stats, "avg_hit_latency_ms")
        assert hasattr(stats, "avg_miss_latency_ms")
        assert hasattr(stats, "latency_reduction_percent")


class TestLogSearchMetrics:
    """log_search_metrics のテスト."""

    def test_logs_metrics_successfully(self) -> None:
        """メトリクスが正常にログ出力されること."""
        metrics = SearchMetrics(
            total_time_ms=100.0,
            embedding_time_ms=20.0,
            lookup_time_ms=5.0,
            search_time_ms=70.0,
            cache_write_time_ms=5.0,
            cache_hit=False,
            similarity_score=0.85,
        )
        # log_search_metrics uses the module-level logger (mocked during import)
        # Should not raise
        log_search_metrics(metrics)

    def test_handles_logging_exception(self) -> None:
        """ログ出力で例外が発生してもリクエスト処理を中断しないこと."""
        # Force the logger to raise by patching the module's logger
        original_logger = _metrics_mod.logger
        mock_logger = MagicMock()
        mock_logger.info.side_effect = RuntimeError("logging failed")
        _metrics_mod.logger = mock_logger

        try:
            metrics = SearchMetrics(
                total_time_ms=100.0,
                embedding_time_ms=20.0,
                lookup_time_ms=5.0,
                search_time_ms=70.0,
                cache_write_time_ms=5.0,
                cache_hit=False,
                similarity_score=0.85,
            )
            # Should not raise
            log_search_metrics(metrics)
            mock_logger.error.assert_called_once()
        finally:
            _metrics_mod.logger = original_logger


class TestLogCacheStats:
    """log_cache_stats のテスト."""

    def test_logs_stats_successfully(self) -> None:
        """キャッシュ統計が正常にログ出力されること."""
        stats = CacheStats(
            total_requests=10,
            cache_hits=3,
            cache_misses=7,
            hit_rate_percent=30.0,
            avg_hit_latency_ms=10.0,
            avg_miss_latency_ms=100.0,
            latency_reduction_percent=90.0,
        )
        # Should not raise
        log_cache_stats(stats)

    def test_handles_logging_exception(self) -> None:
        """ログ出力で例外が発生してもリクエスト処理を中断しないこと."""
        original_logger = _metrics_mod.logger
        mock_logger = MagicMock()
        mock_logger.info.side_effect = RuntimeError("logging failed")
        _metrics_mod.logger = mock_logger

        try:
            stats = CacheStats(
                total_requests=10,
                cache_hits=3,
                cache_misses=7,
                hit_rate_percent=30.0,
                avg_hit_latency_ms=10.0,
                avg_miss_latency_ms=100.0,
                latency_reduction_percent=90.0,
            )
            # Should not raise
            log_cache_stats(stats)
            mock_logger.error.assert_called_once()
        finally:
            _metrics_mod.logger = original_logger


# --- プロパティテスト: レスポンスメトリクスの完全性 ---


class TestProperty8ResponseMetricsCompleteness:
    """Property 8: レスポンスメトリクスの完全性.

    任意のキャッシュヒットレスポンスに対して結果返却時間が含まれ、
    任意のキャッシュミスレスポンスに対して Aurora 検索時間と
    キャッシュ書き込み時間がそれぞれ個別に含まれること。

    **Validates: Requirements 6.2, 6.3**
    Feature: semantic-cache, Property 8: レスポンスメトリクスの完全性
    """

    @given(
        total_time_ms=st.floats(
            min_value=0.01, max_value=10000.0,
            allow_nan=False, allow_infinity=False,
        ),
        embedding_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        lookup_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        similarity_score=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_hit_has_total_time(
        self,
        total_time_ms: float,
        embedding_time_ms: float,
        lookup_time_ms: float,
        similarity_score: float,
    ) -> None:
        """キャッシュヒット時に結果返却時間（total_time_ms）が含まれ正の値であること."""
        metrics = SearchMetrics(
            total_time_ms=total_time_ms,
            embedding_time_ms=embedding_time_ms,
            lookup_time_ms=lookup_time_ms,
            search_time_ms=None,
            cache_write_time_ms=None,
            cache_hit=True,
            similarity_score=similarity_score,
        )

        # キャッシュヒット時: total_time_ms が存在し正の値
        assert metrics.total_time_ms is not None, (
            "Cache hit response must include total_time_ms"
        )
        assert metrics.total_time_ms > 0, (
            f"Cache hit total_time_ms must be > 0, got {metrics.total_time_ms}"
        )
        # キャッシュヒット時: lookup_time_ms が存在する
        assert metrics.lookup_time_ms is not None, (
            "Cache hit response must include lookup_time_ms"
        )

    @given(
        total_time_ms=st.floats(
            min_value=0.01, max_value=10000.0,
            allow_nan=False, allow_infinity=False,
        ),
        embedding_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        lookup_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        search_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        cache_write_time_ms=st.floats(
            min_value=0.01, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        similarity_score=st.one_of(
            st.none(),
            st.floats(
                min_value=0.0, max_value=1.0,
                allow_nan=False, allow_infinity=False,
            ),
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_miss_has_search_and_write_times(
        self,
        total_time_ms: float,
        embedding_time_ms: float,
        lookup_time_ms: float,
        search_time_ms: float,
        cache_write_time_ms: float,
        similarity_score: float | None,
    ) -> None:
        """キャッシュミス時に Aurora 検索時間とキャッシュ書き込み時間が個別に含まれること."""
        metrics = SearchMetrics(
            total_time_ms=total_time_ms,
            embedding_time_ms=embedding_time_ms,
            lookup_time_ms=lookup_time_ms,
            search_time_ms=search_time_ms,
            cache_write_time_ms=cache_write_time_ms,
            cache_hit=False,
            similarity_score=similarity_score,
        )

        # キャッシュミス時: search_time_ms が存在する（Aurora 検索時間）
        assert metrics.search_time_ms is not None, (
            "Cache miss response must include search_time_ms (Aurora search time)"
        )
        # キャッシュミス時: cache_write_time_ms が存在する（キャッシュ書き込み時間）
        assert metrics.cache_write_time_ms is not None, (
            "Cache miss response must include cache_write_time_ms"
        )


# --- Hypothesis Strategies ---


def search_metrics_strategy(cache_hit: bool | None = None) -> st.SearchStrategy[object]:
    """SearchMetrics のストラテジー.

    Args:
        cache_hit: 固定する場合は True/False、ランダムの場合は None
    """
    hit_strategy = st.just(cache_hit) if cache_hit is not None else st.booleans()
    return st.builds(
        SearchMetrics,
        total_time_ms=st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False),
        embedding_time_ms=st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False),
        ),
        lookup_time_ms=st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False),
        ),
        search_time_ms=st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False),
        ),
        cache_write_time_ms=st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False),
        ),
        cache_hit=hit_strategy,
        similarity_score=st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ),
    )


class TestProperty9CacheStatsCalculationAccuracy:
    """Property 9: キャッシュ統計算出の正確性.

    任意の10件以上の SearchMetrics リストに対して、算出されるキャッシュヒット率は
    (ヒット数 / 総数) * 100 と等しく、平均レイテンシ削減率は
    (1 - ヒット時平均レイテンシ / ミス時平均レイテンシ) * 100 と等しいこと。

    **Validates: Requirements 6.4**
    Feature: semantic-cache, Property 9: キャッシュ統計算出の正確性
    """

    @given(
        metrics_list=st.lists(
            search_metrics_strategy(),
            min_size=10,
            max_size=100,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_hit_rate_percent_equals_hits_over_total_times_100(
        self, metrics_list: list[object]
    ) -> None:
        """キャッシュヒット率が (ヒット数 / 総数) * 100 と等しいこと."""
        stats = calculate_cache_stats(metrics_list)

        total = len(metrics_list)
        hits = sum(1 for m in metrics_list if m.cache_hit)

        expected_hit_rate = (hits / total) * 100
        assert stats.hit_rate_percent == pytest.approx(expected_hit_rate)

    @given(
        hit_metrics=st.lists(
            search_metrics_strategy(cache_hit=True),
            min_size=1,
            max_size=50,
        ),
        miss_metrics=st.lists(
            search_metrics_strategy(cache_hit=False),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_latency_reduction_percent_when_both_hits_and_misses_exist(
        self, hit_metrics: list[object], miss_metrics: list[object]
    ) -> None:
        """ヒットとミスが両方存在する場合、平均レイテンシ削減率が正しく算出されること."""
        # 10件以上になるようにリストを結合
        metrics_list = hit_metrics + miss_metrics
        if len(metrics_list) < 10:
            # 足りない分をミスで補完
            additional = [
                SearchMetrics(
                    total_time_ms=100.0,
                    embedding_time_ms=20.0,
                    lookup_time_ms=5.0,
                    search_time_ms=70.0,
                    cache_write_time_ms=5.0,
                    cache_hit=False,
                    similarity_score=0.5,
                )
                for _ in range(10 - len(metrics_list))
            ]
            metrics_list = metrics_list + additional

        stats = calculate_cache_stats(metrics_list)

        # 手動で期待値を算出
        hits = [m for m in metrics_list if m.cache_hit]
        misses = [m for m in metrics_list if not m.cache_hit]

        avg_hit_latency = sum(m.total_time_ms for m in hits) / len(hits)
        avg_miss_latency = sum(m.total_time_ms for m in misses) / len(misses)

        expected_reduction = (1 - avg_hit_latency / avg_miss_latency) * 100

        assert stats.latency_reduction_percent == pytest.approx(expected_reduction)

    @given(
        metrics_list=st.lists(
            search_metrics_strategy(),
            min_size=10,
            max_size=100,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_total_requests_equals_list_length(
        self, metrics_list: list[object]
    ) -> None:
        """total_requests がリストの長さと等しいこと."""
        stats = calculate_cache_stats(metrics_list)
        assert stats.total_requests == len(metrics_list)

    @given(
        metrics_list=st.lists(
            search_metrics_strategy(),
            min_size=10,
            max_size=100,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_hits_plus_misses_equals_total(
        self, metrics_list: list[object]
    ) -> None:
        """cache_hits + cache_misses が total_requests と等しいこと."""
        stats = calculate_cache_stats(metrics_list)
        assert stats.cache_hits + stats.cache_misses == stats.total_requests
