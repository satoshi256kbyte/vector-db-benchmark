"""Embedding 生成モジュールのユニットテスト."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from embedding import EmbeddingError, EmbeddingResult, generate_embedding


class TestEmbeddingResult:
    """EmbeddingResult dataclass のテスト."""

    def test_create_embedding_result(self) -> None:
        """EmbeddingResult が正しく生成されること."""
        embedding = [0.1] * 1024
        result = EmbeddingResult(embedding=embedding, time_ms=5.0)
        assert result.embedding == embedding
        assert result.time_ms == 5.0


class TestGenerateEmbedding:
    """generate_embedding 関数のテスト."""

    def test_empty_string_raises_value_error(self) -> None:
        """空文字列で ValueError が発生すること."""
        with pytest.raises(ValueError, match="入力テキストが空です"):
            generate_embedding("")

    def test_whitespace_only_raises_value_error(self) -> None:
        """空白のみの文字列で ValueError が発生すること."""
        with pytest.raises(ValueError, match="入力テキストが空です"):
            generate_embedding("   ")

    @patch("embedding._get_bedrock_client")
    def test_successful_embedding_generation(self, mock_get_client: MagicMock) -> None:
        """正常にembeddingが生成されること."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        expected_embedding = [0.1] * 1024
        response_body = json.dumps({"embedding": expected_embedding}).encode()
        mock_response_body = MagicMock()
        mock_response_body.read.return_value = response_body
        mock_client.invoke_model.return_value = {"body": mock_response_body}

        result = generate_embedding("テスト入力")

        assert result.embedding == expected_embedding
        assert result.time_ms >= 0
        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "テスト入力"
        assert body["dimensions"] == 1024
        assert body["normalize"] is True

    @patch("embedding._get_bedrock_client")
    def test_timeout_raises_embedding_error(self, mock_get_client: MagicMock) -> None:
        """タイムアウト時に EmbeddingError が発生すること."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.invoke_model.side_effect = ReadTimeoutError(endpoint_url="https://bedrock.example.com")

        with pytest.raises(EmbeddingError, match="タイムアウト"):
            generate_embedding("テスト入力")

    @patch("embedding._get_bedrock_client")
    def test_client_error_raises_embedding_error(self, mock_get_client: MagicMock) -> None:
        """ClientError 時に EmbeddingError が発生すること."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.invoke_model.side_effect = ClientError(
            error_response={"Error": {"Code": "ServiceUnavailable", "Message": "Service unavailable"}},
            operation_name="InvokeModel",
        )

        with pytest.raises(EmbeddingError, match="Bedrock API エラー"):
            generate_embedding("テスト入力")

    @patch("embedding._get_bedrock_client")
    def test_unexpected_error_raises_embedding_error(self, mock_get_client: MagicMock) -> None:
        """予期しないエラー時に EmbeddingError が発生すること."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.invoke_model.side_effect = RuntimeError("unexpected")

        with pytest.raises(EmbeddingError, match="予期しないエラー"):
            generate_embedding("テスト入力")
