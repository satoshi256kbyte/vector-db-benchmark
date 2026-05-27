"""Embedding 生成モジュール.

Bedrock Titan Embeddings V2 呼び出しによるベクトル生成を担当する。
"""

import json
import time
from dataclasses import dataclass

import boto3
from aws_lambda_powertools import Logger
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError

logger = Logger(service="memorydb-semantic-cache")

MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024
TIMEOUT_SECONDS = 10
MAX_TOKEN_LIMIT = 8192
CHARS_PER_TOKEN_ESTIMATE = 4
MAX_CHAR_LIMIT = MAX_TOKEN_LIMIT * CHARS_PER_TOKEN_ESTIMATE


class EmbeddingError(Exception):
    """Bedrock Embedding 呼び出し失敗時の例外."""


class EmbeddingTimeoutError(EmbeddingError):
    """Bedrock Embedding 呼び出しタイムアウト時の例外."""


@dataclass
class EmbeddingResult:
    """Embedding 生成結果.

    Attributes:
        embedding: 1024次元の浮動小数点数ベクトル
        time_ms: 生成所要時間（ミリ秒）
    """

    embedding: list[float]
    time_ms: int


def generate_embedding(text: str) -> EmbeddingResult:
    """Bedrock Titan Embeddings V2 でテキストをベクトル化する.

    Args:
        text: 入力テキスト（1〜8192トークン）

    Returns:
        EmbeddingResult: embedding ベクトルと生成所要時間

    Raises:
        ValueError: 入力が空文字列または空白のみの場合
        ValueError: 入力が8192トークンを超過する場合
        EmbeddingTimeoutError: Bedrock 呼び出しが10秒以内に応答しない場合
        EmbeddingError: Bedrock 呼び出し失敗時
    """
    _validate_input(text)

    bedrock_config = Config(
        read_timeout=TIMEOUT_SECONDS,
        connect_timeout=TIMEOUT_SECONDS,
        retries={"max_attempts": 0},
    )
    client = boto3.client("bedrock-runtime", config=bedrock_config)

    request_body = json.dumps(
        {
            "inputText": text,
            "dimensions": EMBEDDING_DIMENSION,
        }
    )

    start_time = time.monotonic()

    try:
        response = client.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=request_body,
        )
    except ReadTimeoutError as exc:
        logger.error(
            "bedrock_embedding_timeout",
            extra={"model_id": MODEL_ID, "timeout_seconds": TIMEOUT_SECONDS},
        )
        raise EmbeddingTimeoutError(f"Bedrock Embedding 呼び出しが{TIMEOUT_SECONDS}秒以内に応答しませんでした") from exc
    except ClientError as exc:
        logger.error(
            "bedrock_embedding_error",
            extra={"model_id": MODEL_ID, "error": str(exc)},
        )
        raise EmbeddingError(f"Bedrock Embedding 呼び出しに失敗しました: {exc}") from exc
    except Exception as exc:
        logger.error(
            "bedrock_embedding_unexpected_error",
            extra={"model_id": MODEL_ID, "error": str(exc)},
        )
        raise EmbeddingError(f"Bedrock Embedding 呼び出し中に予期しないエラーが発生しました: {exc}") from exc

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    response_body = json.loads(response["body"].read())
    embedding: list[float] = response_body["embedding"]

    return EmbeddingResult(embedding=embedding, time_ms=elapsed_ms)


def _validate_input(text: str) -> None:
    """入力テキストのバリデーションを行う.

    Args:
        text: 入力テキスト

    Raises:
        ValueError: 入力が空文字列または空白のみの場合
        ValueError: 入力が8192トークンを超過する場合（文字数ベースの近似チェック）
    """
    if not text or not text.strip():
        raise ValueError("入力テキストが空文字列または空白文字のみです")

    if len(text) > MAX_CHAR_LIMIT:
        raise ValueError(
            f"入力テキストが8192トークンの上限を超過しています（約{len(text) // CHARS_PER_TOKEN_ESTIMATE}トークン）"
        )
