"""Bedrock Titan Embeddings V2 によるテキストベクトル化モジュール."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError


class EmbeddingError(Exception):
    """Bedrock 呼び出し失敗時の例外.

    Attributes:
        message: エラーメッセージ
    """

    def __init__(self, message: str) -> None:
        """EmbeddingError を初期化する.

        Args:
            message: エラーメッセージ
        """
        super().__init__(message)
        self.message = message


@dataclass
class EmbeddingResult:
    """Embedding 生成結果.

    Attributes:
        embedding: 1024次元の浮動小数点数配列
        time_ms: 生成所要時間（ミリ秒）
    """

    embedding: list[float]
    time_ms: float


_MODEL_ID = "amazon.titan-embed-text-v2:0"
_BEDROCK_CONFIG = Config(
    read_timeout=10,
    retries={"max_attempts": 0},
)


def _get_bedrock_client() -> boto3.client:
    """Bedrock Runtime クライアントを取得する.

    Returns:
        boto3 bedrock-runtime クライアント
    """
    return boto3.client("bedrock-runtime", config=_BEDROCK_CONFIG)


def generate_embedding(text: str) -> EmbeddingResult:
    """Bedrock Titan Embeddings V2 でテキストをベクトル化.

    Args:
        text: 入力テキスト（1〜8192トークン）

    Returns:
        EmbeddingResult（embedding ベクトルと所要時間）

    Raises:
        ValueError: 入力が空文字列の場合
        EmbeddingError: Bedrock 呼び出し失敗時
    """
    if not text or not text.strip():
        msg = "入力テキストが空です"
        raise ValueError(msg)

    client = _get_bedrock_client()
    body = json.dumps({
        "inputText": text,
        "dimensions": 1024,
        "normalize": True,
    })

    start = time.monotonic()
    try:
        response = client.invoke_model(
            modelId=_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
    except ReadTimeoutError as exc:
        msg = f"Bedrock 呼び出しがタイムアウトしました: {exc}"
        raise EmbeddingError(msg) from exc
    except ClientError as exc:
        msg = f"Bedrock API エラー: {exc}"
        raise EmbeddingError(msg) from exc
    except Exception as exc:
        msg = f"Bedrock 呼び出し中に予期しないエラーが発生しました: {exc}"
        raise EmbeddingError(msg) from exc

    elapsed_ms = (time.monotonic() - start) * 1000

    response_body = json.loads(response["body"].read())
    embedding: list[float] = response_body["embedding"]

    return EmbeddingResult(embedding=embedding, time_ms=elapsed_ms)
