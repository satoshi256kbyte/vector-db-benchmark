"""Embedding 生成モジュールのユニットテスト."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

# functions/memorydb-semantic-cache/embedding.py を直接ロード（sys.path 汚染なし）
_FUNC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "functions" / "memorydb-semantic-cache"
_EMBEDDING_PATH = _FUNC_DIR / "embedding.py"

# モジュール名を固定して sys.modules に登録（@patch で参照可能にする）
_MODULE_NAME = "memorydb_embedding"


def _load_embedding_module() -> ModuleType:
    """embedding モジュールを aws_lambda_powertools モック付きでロードする."""
    mock_powertools = MagicMock()
    mock_logger = MagicMock()
    mock_powertools.Logger.return_value = mock_logger

    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _EMBEDDING_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    # aws_lambda_powertools をモックに差し替えてからロード
    original_powertools = sys.modules.get("aws_lambda_powertools")
    sys.modules["aws_lambda_powertools"] = mock_powertools
    try:
        spec.loader.exec_module(module)
    finally:
        if original_powertools is None:
            sys.modules.pop("aws_lambda_powertools", None)
        else:
            sys.modules["aws_lambda_powertools"] = original_powertools

    # sys.modules に登録して @patch で参照可能にする
    sys.modules[_MODULE_NAME] = module
    return module


_embedding_module = _load_embedding_module()
EmbeddingResult = _embedding_module.EmbeddingResult
EmbeddingError = _embedding_module.EmbeddingError
EmbeddingTimeoutError = _embedding_module.EmbeddingTimeoutError
generate_embedding = _embedding_module.generate_embedding
EMBEDDING_DIMENSION = _embedding_module.EMBEDDING_DIMENSION
MAX_TOKEN_LIMIT = _embedding_module.MAX_TOKEN_LIMIT
CHARS_PER_TOKEN_ESTIMATE = _embedding_module.CHARS_PER_TOKEN_ESTIMATE
MAX_CHAR_LIMIT = _embedding_module.MAX_CHAR_LIMIT
_validate_input = _embedding_module._validate_input


def _make_bedrock_response(embedding: list[float]) -> dict[str, MagicMock]:
    """Bedrock レスポンスのモックを作成する."""
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps({"embedding": embedding}).encode()
    return {"body": mock_body}


class TestValidateInput:
    """入力バリデーションのテスト."""

    def test_empty_string_raises_value_error(self) -> None:
        """空文字列の場合 ValueError が発生すること."""
        with pytest.raises(ValueError, match="空文字列または空白文字のみ"):
            _validate_input("")

    def test_whitespace_only_raises_value_error(self) -> None:
        """空白文字のみの場合 ValueError が発生すること."""
        with pytest.raises(ValueError, match="空文字列または空白文字のみ"):
            _validate_input("   ")

    def test_tabs_and_newlines_only_raises_value_error(self) -> None:
        """タブ・改行のみの場合 ValueError が発生すること."""
        with pytest.raises(ValueError, match="空文字列または空白文字のみ"):
            _validate_input("\t\n\r ")

    def test_token_limit_exceeded_raises_value_error(self) -> None:
        """8192トークン超過の場合 ValueError が発生すること."""
        long_text = "a" * (MAX_CHAR_LIMIT + 1)
        with pytest.raises(ValueError, match="8192トークンの上限を超過"):
            _validate_input(long_text)

    def test_text_at_exact_char_limit_passes(self) -> None:
        """文字数が上限ちょうどの場合はバリデーションを通過すること."""
        text = "a" * MAX_CHAR_LIMIT
        _validate_input(text)

    def test_valid_text_passes(self) -> None:
        """有効なテキストはバリデーションを通過すること."""
        _validate_input("テスト入力")


class TestGenerateEmbedding:
    """generate_embedding 関数のテスト."""

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_successful_embedding_generation(self, mock_boto3_client: MagicMock) -> None:
        """正常にembeddingが生成されること."""
        expected_embedding = [0.1] * EMBEDDING_DIMENSION
        mock_boto3_client.return_value.invoke_model.return_value = _make_bedrock_response(expected_embedding)

        result = generate_embedding("テスト入力")

        assert isinstance(result, EmbeddingResult)
        assert result.embedding == expected_embedding
        assert len(result.embedding) == EMBEDDING_DIMENSION
        assert result.time_ms >= 0

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_timeout_raises_embedding_timeout_error(self, mock_boto3_client: MagicMock) -> None:
        """タイムアウト時に EmbeddingTimeoutError が発生すること."""
        mock_boto3_client.return_value.invoke_model.side_effect = ReadTimeoutError(endpoint_url="https://bedrock.test")

        with pytest.raises(EmbeddingTimeoutError):
            generate_embedding("テスト入力")

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_client_error_raises_embedding_error(self, mock_boto3_client: MagicMock) -> None:
        """ClientError 時に EmbeddingError が発生すること."""
        mock_boto3_client.return_value.invoke_model.side_effect = ClientError(
            error_response={"Error": {"Code": "ServiceException", "Message": "Service error"}},
            operation_name="InvokeModel",
        )

        with pytest.raises(EmbeddingError):
            generate_embedding("テスト入力")

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_unexpected_error_raises_embedding_error(self, mock_boto3_client: MagicMock) -> None:
        """予期しないエラー時に EmbeddingError が発生すること."""
        mock_boto3_client.return_value.invoke_model.side_effect = RuntimeError("unexpected")

        with pytest.raises(EmbeddingError):
            generate_embedding("テスト入力")

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_time_ms_is_measured(self, mock_boto3_client: MagicMock) -> None:
        """time_ms が計測されること."""
        expected_embedding = [0.5] * EMBEDDING_DIMENSION
        mock_boto3_client.return_value.invoke_model.return_value = _make_bedrock_response(expected_embedding)

        result = generate_embedding("テスト")

        assert isinstance(result.time_ms, int)
        assert result.time_ms >= 0

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_bedrock_client_configured_with_timeout(self, mock_boto3_client: MagicMock) -> None:
        """Bedrock クライアントがタイムアウト設定で構成されること."""
        expected_embedding = [0.1] * EMBEDDING_DIMENSION
        mock_boto3_client.return_value.invoke_model.return_value = _make_bedrock_response(expected_embedding)

        generate_embedding("テスト")

        mock_boto3_client.assert_called_once()
        call_kwargs = mock_boto3_client.call_args
        assert call_kwargs[0][0] == "bedrock-runtime"
        config = call_kwargs[1]["config"]
        assert config.read_timeout == 10
        assert config.connect_timeout == 10

    @patch(f"{_MODULE_NAME}.boto3.client")
    def test_invoke_model_called_with_correct_params(self, mock_boto3_client: MagicMock) -> None:
        """invoke_model が正しいパラメータで呼ばれること."""
        expected_embedding = [0.1] * EMBEDDING_DIMENSION
        mock_boto3_client.return_value.invoke_model.return_value = _make_bedrock_response(expected_embedding)

        generate_embedding("テスト入力テキスト")

        call_kwargs = mock_boto3_client.return_value.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"

        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "テスト入力テキスト"
        assert body["dimensions"] == 1024

    def test_empty_string_raises_without_bedrock_call(self) -> None:
        """空文字列の場合、Bedrock 呼び出しなしで ValueError が発生すること."""
        with pytest.raises(ValueError):
            generate_embedding("")

    def test_embedding_timeout_error_is_subclass_of_embedding_error(self) -> None:
        """EmbeddingTimeoutError が EmbeddingError のサブクラスであること."""
        assert issubclass(EmbeddingTimeoutError, EmbeddingError)


class TestConstants:
    """定数のテスト."""

    def test_embedding_dimension(self) -> None:
        """EMBEDDING_DIMENSION が 1024 であること."""
        assert EMBEDDING_DIMENSION == 1024

    def test_max_token_limit(self) -> None:
        """MAX_TOKEN_LIMIT が 8192 であること."""
        assert MAX_TOKEN_LIMIT == 8192

    def test_chars_per_token_estimate(self) -> None:
        """CHARS_PER_TOKEN_ESTIMATE が 4 であること."""
        assert CHARS_PER_TOKEN_ESTIMATE == 4

    def test_max_char_limit(self) -> None:
        """MAX_CHAR_LIMIT が 32768 であること."""
        assert MAX_CHAR_LIMIT == 32768
