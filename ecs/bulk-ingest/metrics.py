"""メトリクス収集・出力モジュール."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IngestionPhaseMetrics:
    """各フェーズの計測結果.

    Attributes:
        phase: フェーズ名（"index_drop", "data_insert", "index_create"）
        duration_seconds: フェーズの所要時間（秒）
        record_count: レコード数（data_insert フェーズのみ有効）
    """

    phase: str
    duration_seconds: float
    record_count: int


@dataclass
class DatabaseIngestionResult:
    """各DBの投入結果.

    Attributes:
        database: データベース識別子
        phases: 各フェーズの計測結果リスト
        total_duration_seconds: 全フェーズの合計所要時間
        throughput_records_per_sec: スループット（レコード/秒）
        record_count: 投入レコード数
        success: 成否
        error_message: エラーメッセージ（成功時はNone）
    """

    database: str
    phases: list[IngestionPhaseMetrics]
    total_duration_seconds: float
    throughput_records_per_sec: float
    record_count: int
    success: bool
    error_message: str | None = None


@dataclass
class IngestionReport:
    """投入ECSタスク全体のレポート.

    Attributes:
        aurora: Aurora (pgvector) の投入結果
        opensearch: OpenSearch Serverless の投入結果
        s3vectors: Amazon S3 Vectors の投入結果
        record_count: 投入レコード数
        vector_dimension: ベクトル次元数
    """

    aurora: DatabaseIngestionResult
    opensearch: DatabaseIngestionResult
    s3vectors: DatabaseIngestionResult
    record_count: int
    vector_dimension: int


def calculate_throughput(record_count: int, duration_seconds: float) -> float:
    """スループットを算出する.

    Args:
        record_count: 投入レコード数
        duration_seconds: 所要時間（秒）

    Returns:
        スループット（レコード/秒）

    Raises:
        ValueError: duration_seconds が 0 以下の場合
    """
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}")
    return record_count / duration_seconds


def calculate_total_duration(phases: list[IngestionPhaseMetrics]) -> float:
    """フェーズの合計所要時間を算出する.

    Args:
        phases: フェーズ計測結果のリスト

    Returns:
        合計所要時間（秒）
    """
    return sum(p.duration_seconds for p in phases)
