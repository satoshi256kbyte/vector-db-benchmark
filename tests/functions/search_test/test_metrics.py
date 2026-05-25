"""メトリクス計測モジュールのテスト."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


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
