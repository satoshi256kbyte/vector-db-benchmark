"""models.py のユニットテスト."""

import importlib.util
import time
from pathlib import Path
from types import ModuleType

# functions/memorydb-semantic-cache/models.py を直接ロード（sys.path 汚染なし）
_FUNC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "functions" / "memorydb-semantic-cache"
_MODELS_PATH = _FUNC_DIR / "models.py"
_spec = importlib.util.spec_from_file_location("memorydb_models", _MODELS_PATH)
assert _spec is not None
assert _spec.loader is not None
_memorydb_models: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_memorydb_models)

CacheEntry = _memorydb_models.CacheEntry
CacheMetadata = _memorydb_models.CacheMetadata
SearchMetrics = _memorydb_models.SearchMetrics
SemanticCacheResponse = _memorydb_models.SemanticCacheResponse
CacheStats = _memorydb_models.CacheStats


class TestCacheEntry:
    """CacheEntry dataclass のテスト."""

    def test_create_with_defaults(self) -> None:
        """デフォルト TTL でエントリを作成できること."""
        entry = CacheEntry(
            id="test-uuid",
            query_embedding=[0.1] * 1024,
            query_text="テストクエリ",
            result="テスト結果",
            created_at=int(time.time()),
        )
        assert entry.ttl_seconds == 3600

    def test_create_with_custom_ttl(self) -> None:
        """カスタム TTL でエントリを作成できること."""
        entry = CacheEntry(
            id="test-uuid",
            query_embedding=[0.5] * 1024,
            query_text="クエリ",
            result="結果",
            created_at=1000000,
            ttl_seconds=7200,
        )
        assert entry.ttl_seconds == 7200
        assert entry.id == "test-uuid"
        assert len(entry.query_embedding) == 1024


class TestCacheMetadata:
    """CacheMetadata dataclass のテスト."""

    def test_cache_hit(self) -> None:
        """キャッシュヒット時のメタデータ."""
        meta = CacheMetadata(hit=True, similarity_score=0.97, lookup_time_ms=2)
        assert meta.hit is True
        assert meta.similarity_score == 0.97
        assert meta.lookup_time_ms == 2

    def test_cache_miss_no_similar(self) -> None:
        """類似エントリなしのキャッシュミス時のメタデータ."""
        meta = CacheMetadata(hit=False, similarity_score=None, lookup_time_ms=5)
        assert meta.hit is False
        assert meta.similarity_score is None


class TestSearchMetrics:
    """SearchMetrics dataclass のテスト."""

    def test_cache_hit_metrics(self) -> None:
        """キャッシュヒット時のメトリクス."""
        metrics = SearchMetrics(
            total_time_ms=15,
            embedding_time_ms=8,
            lookup_time_ms=2,
            fm_time_ms=None,
            cache_write_time_ms=None,
            cache_hit=True,
            similarity_score=0.97,
        )
        assert metrics.cache_hit is True
        assert metrics.fm_time_ms is None
        assert metrics.cache_write_time_ms is None

    def test_cache_miss_metrics(self) -> None:
        """キャッシュミス時のメトリクス."""
        metrics = SearchMetrics(
            total_time_ms=500,
            embedding_time_ms=10,
            lookup_time_ms=3,
            fm_time_ms=450,
            cache_write_time_ms=5,
            cache_hit=False,
            similarity_score=0.8,
        )
        assert metrics.cache_hit is False
        assert metrics.fm_time_ms == 450
        assert metrics.cache_write_time_ms == 5


class TestSemanticCacheResponse:
    """SemanticCacheResponse dataclass のテスト."""

    def test_to_dict_cache_hit(self) -> None:
        """キャッシュヒット時の to_dict() 出力."""
        response = SemanticCacheResponse(
            result="テスト結果",
            cache=CacheMetadata(hit=True, similarity_score=0.97, lookup_time_ms=2),
            metrics=SearchMetrics(
                total_time_ms=15,
                embedding_time_ms=8,
                lookup_time_ms=2,
                fm_time_ms=None,
                cache_write_time_ms=None,
                cache_hit=True,
                similarity_score=0.97,
            ),
        )
        result = response.to_dict()

        assert result["result"] == "テスト結果"
        assert result["cache"] == {
            "hit": True,
            "similarity_score": 0.97,
            "lookup_time_ms": 2,
        }
        assert result["metrics"] == {
            "total_time_ms": 15,
            "embedding_time_ms": 8,
            "lookup_time_ms": 2,
            "fm_time_ms": None,
            "cache_write_time_ms": None,
            "cache_hit": True,
            "similarity_score": 0.97,
        }

    def test_to_dict_cache_miss(self) -> None:
        """キャッシュミス時の to_dict() 出力."""
        response = SemanticCacheResponse(
            result="FM結果",
            cache=CacheMetadata(hit=False, similarity_score=0.8, lookup_time_ms=3),
            metrics=SearchMetrics(
                total_time_ms=500,
                embedding_time_ms=10,
                lookup_time_ms=3,
                fm_time_ms=450,
                cache_write_time_ms=5,
                cache_hit=False,
                similarity_score=0.8,
            ),
        )
        result = response.to_dict()

        assert result["result"] == "FM結果"
        assert result["cache"]["hit"] is False
        assert result["metrics"]["fm_time_ms"] == 450
        assert result["metrics"]["cache_write_time_ms"] == 5


class TestCacheStats:
    """CacheStats dataclass のテスト."""

    def test_create_stats(self) -> None:
        """統計情報を作成できること."""
        stats = CacheStats(
            total_requests=100,
            cache_hits=75,
            cache_misses=25,
            hit_rate_percent=75.0,
            avg_hit_latency_ms=5.2,
            avg_miss_latency_ms=450.0,
            latency_reduction_percent=98.8,
        )
        assert stats.total_requests == 100
        assert stats.cache_hits == 75
        assert stats.cache_misses == 25
        assert stats.hit_rate_percent == 75.0
        assert stats.avg_hit_latency_ms == 5.2
        assert stats.avg_miss_latency_ms == 450.0
        assert stats.latency_reduction_percent == 98.8
