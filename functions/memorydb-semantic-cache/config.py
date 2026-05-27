"""設定管理モジュール.

環境変数の読み込み・バリデーション・デフォルト値管理を担当する。
"""

import os
from dataclasses import dataclass

from aws_lambda_powertools import Logger

logger = Logger(service="memorydb-semantic-cache")

DEFAULT_MEMORYDB_PORT = 6379
DEFAULT_SIMILARITY_THRESHOLD = 0.95
DEFAULT_CACHE_TTL = 3600

MIN_SIMILARITY_THRESHOLD = 0.0
MAX_SIMILARITY_THRESHOLD = 1.0
MIN_CACHE_TTL = 1
MAX_CACHE_TTL = 604800


@dataclass
class CacheConfig:
    """セマンティックキャッシュ設定.

    Attributes:
        memorydb_endpoint: MemoryDB クラスターエンドポイント
        memorydb_port: MemoryDB ポート番号
        similarity_threshold: キャッシュヒット判定の類似度閾値（0.0〜1.0）
        cache_ttl: キャッシュエントリの有効期限（秒、1〜604800）
    """

    memorydb_endpoint: str
    memorydb_port: int
    similarity_threshold: float
    cache_ttl: int


def load_config() -> CacheConfig:
    """環境変数から設定を読み込み、バリデーションを行う.

    無効な値の場合はデフォルト値を使用し、警告ログを出力する。

    Returns:
        CacheConfig: バリデーション済みの設定オブジェクト

    Raises:
        ValueError: MEMORYDB_ENDPOINT が未設定の場合
    """
    memorydb_endpoint = os.environ.get("MEMORYDB_ENDPOINT", "")
    if not memorydb_endpoint:
        raise ValueError("環境変数 MEMORYDB_ENDPOINT が設定されていません")

    memorydb_port = _parse_memorydb_port()
    similarity_threshold = _parse_similarity_threshold()
    cache_ttl = _parse_cache_ttl()

    return CacheConfig(
        memorydb_endpoint=memorydb_endpoint,
        memorydb_port=memorydb_port,
        similarity_threshold=similarity_threshold,
        cache_ttl=cache_ttl,
    )


def _parse_memorydb_port() -> int:
    """MEMORYDB_PORT 環境変数をパースする.

    Returns:
        パースされたポート番号、無効値の場合はデフォルト値
    """
    raw_value = os.environ.get("MEMORYDB_PORT", "")
    if not raw_value:
        return DEFAULT_MEMORYDB_PORT

    try:
        port = int(raw_value)
        if port <= 0 or port > 65535:
            logger.warning(
                "MEMORYDB_PORT の値が無効です。デフォルト値を使用します",
                extra={"invalid_value": raw_value, "default_value": DEFAULT_MEMORYDB_PORT},
            )
            return DEFAULT_MEMORYDB_PORT
        return port
    except ValueError:
        logger.warning(
            "MEMORYDB_PORT の値が整数として解釈できません。デフォルト値を使用します",
            extra={"invalid_value": raw_value, "default_value": DEFAULT_MEMORYDB_PORT},
        )
        return DEFAULT_MEMORYDB_PORT


def _parse_similarity_threshold() -> float:
    """SIMILARITY_THRESHOLD 環境変数をパースする.

    有効範囲: 0.0〜1.0
    無効値の場合はデフォルト値 0.95 を使用し、警告ログを出力する。

    Returns:
        パースされた類似度閾値
    """
    raw_value = os.environ.get("SIMILARITY_THRESHOLD", "")
    if not raw_value:
        return DEFAULT_SIMILARITY_THRESHOLD

    try:
        threshold = float(raw_value)
        if threshold < MIN_SIMILARITY_THRESHOLD or threshold > MAX_SIMILARITY_THRESHOLD:
            logger.warning(
                "SIMILARITY_THRESHOLD の値が有効範囲外です。デフォルト値を使用します",
                extra={
                    "invalid_value": raw_value,
                    "valid_range": f"{MIN_SIMILARITY_THRESHOLD}〜{MAX_SIMILARITY_THRESHOLD}",
                    "default_value": DEFAULT_SIMILARITY_THRESHOLD,
                },
            )
            return DEFAULT_SIMILARITY_THRESHOLD
        return threshold
    except ValueError:
        logger.warning(
            "SIMILARITY_THRESHOLD の値が浮動小数点数として解釈できません。デフォルト値を使用します",
            extra={"invalid_value": raw_value, "default_value": DEFAULT_SIMILARITY_THRESHOLD},
        )
        return DEFAULT_SIMILARITY_THRESHOLD


def _parse_cache_ttl() -> int:
    """CACHE_TTL 環境変数をパースする.

    有効範囲: 1〜604800（秒）
    無効値の場合はデフォルト値 3600 を使用し、警告ログを出力する。

    Returns:
        パースされた TTL 値
    """
    raw_value = os.environ.get("CACHE_TTL", "")
    if not raw_value:
        return DEFAULT_CACHE_TTL

    try:
        ttl = int(raw_value)
        if ttl < MIN_CACHE_TTL or ttl > MAX_CACHE_TTL:
            logger.warning(
                "CACHE_TTL の値が有効範囲外です。デフォルト値を使用します",
                extra={
                    "invalid_value": raw_value,
                    "valid_range": f"{MIN_CACHE_TTL}〜{MAX_CACHE_TTL}",
                    "default_value": DEFAULT_CACHE_TTL,
                },
            )
            return DEFAULT_CACHE_TTL
        return ttl
    except ValueError:
        logger.warning(
            "CACHE_TTL の値が整数として解釈できません。デフォルト値を使用します",
            extra={"invalid_value": raw_value, "default_value": DEFAULT_CACHE_TTL},
        )
        return DEFAULT_CACHE_TTL
