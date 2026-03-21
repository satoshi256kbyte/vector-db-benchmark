"""動作確認Lambda用データモデル."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DatabaseResult:
    """各データベースの動作確認結果.

    Attributes:
        database: データベース識別子 ("aurora_pgvector", "opensearch", or "s3vectors")
        insert_count: 投入件数
        search_result_count: 検索結果件数
        success: 成否
        error_message: エラーメッセージ（成功時はNone）
    """

    database: str
    insert_count: int
    search_result_count: int
    success: bool
    error_message: str | None = None


@dataclass
class VerifyResponse:
    """動作確認Lambda全体のレスポンス.

    Attributes:
        aurora: Aurora (pgvector) の動作確認結果
        opensearch: OpenSearch Serverless の動作確認結果
        s3vectors: Amazon S3 Vectors の動作確認結果
        vector_dimension: ベクトル次元数 (1536)
        total_vectors: 投入ベクトル数 (5)
    """

    aurora: DatabaseResult
    opensearch: DatabaseResult
    s3vectors: DatabaseResult
    vector_dimension: int
    total_vectors: int

    def to_dict(self) -> dict[str, object]:
        """JSON シリアライズ可能な辞書に変換する.

        Returns:
            データクラスの全フィールドを含む辞書
        """
        return asdict(self)
