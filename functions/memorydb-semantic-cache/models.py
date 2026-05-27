"""データモデル定義モジュール.

セマンティックキャッシュで使用するデータモデルを定義する。
CacheEntry、CacheMetadata、SearchMetrics、SemanticCacheResponse、CacheStats を提供する。
"""

from dataclasses import dataclass


@dataclass
class CacheEntry:
    """セマンティックキャッシュの1エントリ.

    MemoryDB 上では HASH 型で保存される。
    キー形式: cache:{uuid}

    Attributes:
        id: エントリID（UUID）
        query_embedding: クエリ embedding ベクトル（1024次元）
        query_text: 元のクエリテキスト（最大1000文字）
        result: FM 推論結果テキスト
        created_at: 作成タイムスタンプ（Unix epoch 秒）
        ttl_seconds: 有効期限（秒単位、デフォルト3600）
    """

    id: str
    query_embedding: list[float]
    query_text: str
    result: str
    created_at: int
    ttl_seconds: int = 3600


@dataclass
class CacheMetadata:
    """キャッシュメタデータ.

    キャッシュルックアップの結果情報を保持する。

    Attributes:
        hit: キャッシュヒットしたかどうか
        similarity_score: コサイン類似度スコア（0.0〜1.0、該当なしの場合 None）
        lookup_time_ms: キャッシュルックアップ所要時間（ミリ秒）
    """

    hit: bool
    similarity_score: float | None
    lookup_time_ms: int


@dataclass
class SearchMetrics:
    """検索メトリクス.

    各リクエストのパフォーマンス計測結果を保持する。

    Attributes:
        total_time_ms: 全体レスポンス時間（ミリ秒）
        embedding_time_ms: embedding 生成時間（ミリ秒、未計測時 None）
        lookup_time_ms: キャッシュルックアップ時間（ミリ秒、未計測時 None）
        fm_time_ms: FM 呼び出し時間（ミリ秒、未計測時 None）
        cache_write_time_ms: キャッシュ書き込み時間（ミリ秒、未計測時 None）
        cache_hit: キャッシュヒットしたかどうか
        similarity_score: コサイン類似度スコア（0.0〜1.0、該当なしの場合 None）
    """

    total_time_ms: int
    embedding_time_ms: int | None
    lookup_time_ms: int | None
    fm_time_ms: int | None
    cache_write_time_ms: int | None
    cache_hit: bool
    similarity_score: float | None


@dataclass
class SemanticCacheResponse:
    """セマンティックキャッシュレスポンス.

    Lambda 関数のレスポンスボディを構成するデータモデル。

    Attributes:
        result: FM 推論結果テキスト
        cache: キャッシュメタデータ
        metrics: 検索メトリクス
    """

    result: str
    cache: CacheMetadata
    metrics: SearchMetrics

    def to_dict(self) -> dict[str, object]:
        """JSON シリアライズ可能な辞書に変換する.

        Returns:
            レスポンスボディとして使用可能な辞書
        """
        return {
            "result": self.result,
            "cache": {
                "hit": self.cache.hit,
                "similarity_score": self.cache.similarity_score,
                "lookup_time_ms": self.cache.lookup_time_ms,
            },
            "metrics": {
                "total_time_ms": self.metrics.total_time_ms,
                "embedding_time_ms": self.metrics.embedding_time_ms,
                "lookup_time_ms": self.metrics.lookup_time_ms,
                "fm_time_ms": self.metrics.fm_time_ms,
                "cache_write_time_ms": self.metrics.cache_write_time_ms,
                "cache_hit": self.metrics.cache_hit,
                "similarity_score": self.metrics.similarity_score,
            },
        }


@dataclass
class CacheStats:
    """キャッシュ統計.

    複数リクエストのメトリクスから算出されるキャッシュ統計情報。

    Attributes:
        total_requests: 総リクエスト数
        cache_hits: キャッシュヒット数
        cache_misses: キャッシュミス数
        hit_rate_percent: ヒット率（パーセンテージ、小数点以下1桁）
        avg_hit_latency_ms: キャッシュヒット時の平均レイテンシ（ミリ秒）
        avg_miss_latency_ms: キャッシュミス時の平均レイテンシ（ミリ秒）
        latency_reduction_percent: レイテンシ削減率（パーセンテージ、小数点以下1桁）
    """

    total_requests: int
    cache_hits: int
    cache_misses: int
    hit_rate_percent: float
    avg_hit_latency_ms: float
    avg_miss_latency_ms: float
    latency_reduction_percent: float
