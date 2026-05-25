"""パフォーマンス計測・構造化ログ出力モジュール."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from aws_lambda_powertools import Logger

from models import CacheStats

logger = Logger(service="search-test")


@dataclass
class SearchMetrics:
    """検索メトリクス.

    Attributes:
        total_time_ms: 全体レスポンス時間（ミリ秒）
        embedding_time_ms: embedding 生成時間（ミリ秒、計測失敗時はNone）
        lookup_time_ms: キャッシュルックアップ時間（ミリ秒、計測失敗時はNone）
        search_time_ms: Aurora 検索時間（ミリ秒、計測失敗時はNone）
        cache_write_time_ms: キャッシュ書き込み時間（ミリ秒、計測失敗時はNone）
        cache_hit: キャッシュヒット判定
        similarity_score: コサイン類似度スコア（ミス時はNone）
    """

    total_time_ms: float
    embedding_time_ms: float | None
    lookup_time_ms: float | None
    search_time_ms: float | None
    cache_write_time_ms: float | None
    cache_hit: bool
    similarity_score: float | None

    def to_dict(self) -> dict[str, object]:
        """JSON シリアライズ可能な辞書に変換する.

        Returns:
            データクラスの全フィールドを含む辞書
        """
        return asdict(self)


def calculate_cache_stats(
    metrics_list: list[SearchMetrics],
) -> "CacheStats":
    """複数リクエストのメトリクスからキャッシュ統計を算出.

    Args:
        metrics_list: SearchMetrics のリスト

    Returns:
        CacheStats（ヒット率、平均レイテンシ削減率）
    """
    total_requests = len(metrics_list)
    if total_requests == 0:
        return CacheStats(
            total_requests=0,
            cache_hits=0,
            cache_misses=0,
            hit_rate_percent=0.0,
            avg_hit_latency_ms=0.0,
            avg_miss_latency_ms=0.0,
            latency_reduction_percent=0.0,
        )

    hit_metrics = [m for m in metrics_list if m.cache_hit]
    miss_metrics = [m for m in metrics_list if not m.cache_hit]

    cache_hits = len(hit_metrics)
    cache_misses = len(miss_metrics)
    hit_rate_percent = (cache_hits / total_requests) * 100

    avg_hit_latency_ms = (
        sum(m.total_time_ms for m in hit_metrics) / cache_hits if cache_hits > 0 else 0.0
    )
    avg_miss_latency_ms = (
        sum(m.total_time_ms for m in miss_metrics) / cache_misses if cache_misses > 0 else 0.0
    )

    if avg_miss_latency_ms > 0 and cache_hits > 0:
        latency_reduction_percent = (1 - avg_hit_latency_ms / avg_miss_latency_ms) * 100
    else:
        latency_reduction_percent = 0.0

    return CacheStats(
        total_requests=total_requests,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        hit_rate_percent=hit_rate_percent,
        avg_hit_latency_ms=avg_hit_latency_ms,
        avg_miss_latency_ms=avg_miss_latency_ms,
        latency_reduction_percent=latency_reduction_percent,
    )


def log_search_metrics(metrics: SearchMetrics) -> None:
    """検索メトリクスを構造化ログとして出力する.

    メトリクス計測中に例外が発生した場合はエラーをログに記録し、
    リクエスト処理は中断しない。

    Args:
        metrics: 検索メトリクス
    """
    try:
        logger.info(
            "search_metrics",
            total_time_ms=metrics.total_time_ms,
            embedding_time_ms=metrics.embedding_time_ms,
            lookup_time_ms=metrics.lookup_time_ms,
            search_time_ms=metrics.search_time_ms,
            cache_write_time_ms=metrics.cache_write_time_ms,
            cache_hit=metrics.cache_hit,
            similarity_score=metrics.similarity_score,
        )
    except Exception as exc:
        logger.error(
            "metrics_logging_failed",
            error=str(exc),
            action="continue_processing",
        )


def log_cache_stats(stats: "CacheStats") -> None:
    """キャッシュ統計を構造化ログとして出力する.

    Args:
        stats: キャッシュ統計
    """
    try:
        logger.info(
            "cache_stats",
            total_requests=stats.total_requests,
            cache_hits=stats.cache_hits,
            cache_misses=stats.cache_misses,
            hit_rate_percent=stats.hit_rate_percent,
            avg_hit_latency_ms=stats.avg_hit_latency_ms,
            avg_miss_latency_ms=stats.avg_miss_latency_ms,
            latency_reduction_percent=stats.latency_reduction_percent,
        )
    except Exception as exc:
        logger.error(
            "cache_stats_logging_failed",
            error=str(exc),
            action="continue_processing",
        )
