"""検索テスト Lambda データモデル."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SearchTestEvent:
    """検索テスト Lambda のイベントペイロード.

    Attributes:
        search_count: クエリ実行回数
        top_k: 近傍返却件数
        record_count: 投入済みレコード数（クエリベクトル生成用）
    """

    search_count: int = 100
    top_k: int = 10
    record_count: int = 100000


@dataclass
class LatencyStats:
    """レイテンシ統計.

    Attributes:
        avg_ms: 平均レイテンシ（ミリ秒）
        p50_ms: P50 レイテンシ（ミリ秒）
        p95_ms: P95 レイテンシ（ミリ秒）
        p99_ms: P99 レイテンシ（ミリ秒）
        min_ms: 最小レイテンシ（ミリ秒）
        max_ms: 最大レイテンシ（ミリ秒）
    """

    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float


@dataclass
class DatabaseSearchResult:
    """各DBの検索結果.

    Attributes:
        database: データベース識別子
        latency: レイテンシ統計
        throughput_qps: クエリ/秒
        search_count: 検索回数
        top_k: 近傍返却件数
        success: 成否
        error_message: エラーメッセージ（成功時はNone）
    """

    database: str
    latency: LatencyStats
    throughput_qps: float
    search_count: int
    top_k: int
    success: bool
    error_message: str | None = None


@dataclass
class SearchTestResponse:
    """検索テスト Lambda 全体のレスポンス.

    Attributes:
        aurora: Aurora (pgvector) の検索結果
        opensearch: OpenSearch Serverless の検索結果
        s3vectors: Amazon S3 Vectors の検索結果
        search_count: クエリ実行回数
        top_k: 近傍返却件数
        comparison: 比較表形式のデータ
    """

    aurora: DatabaseSearchResult
    opensearch: DatabaseSearchResult
    s3vectors: DatabaseSearchResult
    search_count: int
    top_k: int
    comparison: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """JSON シリアライズ可能な辞書に変換する.

        Returns:
            データクラスの全フィールドを含む辞書
        """
        return asdict(self)
