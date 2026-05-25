"""検索テスト Lambda ハンドラーのユニットテスト.

パラメータバリデーション、デフォルト値、エラーハンドリングを検証する。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis import given, settings
from hypothesis import strategies as st


def _passthrough_decorator(func=None, **kwargs):  # noqa: ANN001, ANN003
    """Powertools デコレータのパススルーモック."""
    if func is not None:
        return func
    return _passthrough_decorator


def _import_search_test_handler() -> ModuleType:
    """functions/search-test/handler.py を外部依存モック付きでインポートする."""
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    mock_powertools = MagicMock()
    mock_logger = MagicMock()
    mock_logger.inject_lambda_context = _passthrough_decorator
    mock_powertools.Logger.return_value = mock_logger
    mock_tracer = MagicMock()
    mock_tracer.capture_lambda_handler = _passthrough_decorator
    mock_tracer.capture_method = _passthrough_decorator
    mock_powertools.Tracer.return_value = mock_tracer

    ext_mocks: dict[str, MagicMock] = {
        "psycopg2": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "opensearchpy": MagicMock(),
        "requests_aws4auth": MagicMock(),
        "aws_lambda_powertools": mock_powertools,
    }

    original_path = sys.path[:]
    saved_modules: dict[str, object] = {}
    for name in [
        "handler", "logic", "models", "vector_generator",
        "embedding", "metrics", "semantic_cache", "cache_store",
    ]:
        saved_modules[name] = sys.modules.pop(name, None)
    saved_ext: dict[str, object] = {}
    for mod_name, mock in ext_mocks.items():
        saved_ext[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

    try:
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)
        module = importlib.import_module("handler")
        return module
    finally:
        sys.path[:] = original_path
        sys.modules.pop("handler", None)
        sys.modules.pop("logic", None)
        sys.modules.pop("models", None)
        sys.modules.pop("vector_generator", None)
        sys.modules.pop("embedding", None)
        sys.modules.pop("metrics", None)
        sys.modules.pop("semantic_cache", None)
        sys.modules.pop("cache_store", None)
        for name, saved in saved_modules.items():
            if saved is not None:
                sys.modules[name] = saved
        for mod_name in ext_mocks:
            if saved_ext[mod_name] is not None:
                sys.modules[mod_name] = saved_ext[mod_name]  # type: ignore[assignment]
            else:
                sys.modules.pop(mod_name, None)


_handler_mod = _import_search_test_handler()
_parse_event = _handler_mod._parse_event
_get_config = _handler_mod._get_config
handler_fn = _handler_mod.handler
semantic_cache_handler_fn = _handler_mod.semantic_cache_handler


class TestParseEvent:
    """_parse_event のパラメータバリデーションテスト."""

    def test_default_values(self) -> None:
        """空イベントでデフォルト値が適用されること."""
        result = _parse_event({})
        assert result.search_count == 100
        assert result.top_k == 10
        assert result.record_count == 100000

    def test_custom_values(self) -> None:
        """カスタム値が正しくパースされること."""
        result = _parse_event({"search_count": 50, "top_k": 5, "record_count": 500})
        assert result.search_count == 50
        assert result.top_k == 5
        assert result.record_count == 500

    def test_string_values_converted(self) -> None:
        """文字列値が整数に変換されること."""
        result = _parse_event({"search_count": "200", "top_k": "20", "record_count": "1000"})
        assert result.search_count == 200
        assert result.top_k == 20
        assert result.record_count == 1000

    def test_search_count_too_low(self) -> None:
        """search_count が下限未満でエラー."""
        with pytest.raises(ValueError, match="search_count"):
            _parse_event({"search_count": 0})

    def test_search_count_too_high(self) -> None:
        """search_count が上限超過でエラー."""
        with pytest.raises(ValueError, match="search_count"):
            _parse_event({"search_count": 10001})

    def test_top_k_too_low(self) -> None:
        """top_k が下限未満でエラー."""
        with pytest.raises(ValueError, match="top_k"):
            _parse_event({"top_k": 0})

    def test_top_k_too_high(self) -> None:
        """top_k が上限超過でエラー."""
        with pytest.raises(ValueError, match="top_k"):
            _parse_event({"top_k": 101})

    def test_record_count_too_low(self) -> None:
        """record_count が下限未満でエラー."""
        with pytest.raises(ValueError, match="record_count"):
            _parse_event({"record_count": 0})

    def test_boundary_values_valid(self) -> None:
        """境界値が正常にパースされること."""
        result = _parse_event({"search_count": 1, "top_k": 1, "record_count": 1})
        assert result.search_count == 1
        assert result.top_k == 1
        assert result.record_count == 1

        result = _parse_event({"search_count": 10000, "top_k": 100})
        assert result.search_count == 10000
        assert result.top_k == 100


class TestHandler:
    """handler 関数のユニットテスト."""

    def test_invalid_params_returns_400(self) -> None:
        """不正パラメータで 400 レスポンスを返すこと."""
        event: dict[str, object] = {"search_count": -1}
        result = handler_fn(event, MagicMock())
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "error" in body

    def test_invalid_type_returns_400(self) -> None:
        """型変換不可の値で 400 レスポンスを返すこと."""
        event: dict[str, object] = {"search_count": "not_a_number"}
        result = handler_fn(event, MagicMock())
        assert result["statusCode"] == 400

    @patch.object(_handler_mod, "run_search_test")
    def test_success_returns_200(self, mock_run: MagicMock) -> None:
        """正常実行で 200 レスポンスを返すこと."""
        mock_response = MagicMock()
        mock_response.to_dict.return_value = {"aurora": {}, "opensearch": {}, "s3vectors": {}}
        mock_run.return_value = mock_response

        event: dict[str, object] = {"search_count": 10, "top_k": 5, "record_count": 100}
        result = handler_fn(event, MagicMock())
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "aurora" in body
        mock_run.assert_called_once_with(search_count=10, top_k=5, record_count=100)

    @patch.object(_handler_mod, "run_search_test", side_effect=RuntimeError("DB connection failed"))
    def test_runtime_error_returns_500(self, mock_run: MagicMock) -> None:
        """実行時エラーで 500 レスポンスを返すこと."""
        event: dict[str, object] = {"search_count": 10, "top_k": 5, "record_count": 100}
        result = handler_fn(event, MagicMock())
        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "DB connection failed" in body["error"]


class TestSemanticCacheHandlerBedrockTimeout:
    """Bedrock タイムアウト時のバイパステスト.

    Requirements 3.3: Bedrock 呼び出しタイムアウト時に Aurora 直接検索にフォールバックする。
    """

    @patch.object(_handler_mod, "_get_aurora_connection")
    @patch.object(_handler_mod, "generate_embedding")
    def test_bedrock_timeout_bypasses_to_aurora(
        self,
        mock_generate_embedding: MagicMock,
        mock_get_aurora_connection: MagicMock,
    ) -> None:
        """Bedrock タイムアウト時に Aurora 直接検索にフォールバックすること."""
        # Arrange: generate_embedding が EmbeddingError を発生させる
        embedding_error = _handler_mod.EmbeddingError("Bedrock タイムアウト")
        mock_generate_embedding.side_effect = embedding_error

        # Aurora 接続のモック
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("結果1: テストコンテンツ", 0.15),
            ("結果2: テストコンテンツ", 0.25),
        ]
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_aurora_connection.return_value = mock_connection

        # Act
        event: dict[str, object] = {"query": "テスト"}
        context = MagicMock()
        response = semantic_cache_handler_fn(event, context)

        # Assert: 200 レスポンスが返ること
        assert response["statusCode"] == 200

        # Assert: レスポンスボディに結果が含まれること
        body = json.loads(response["body"])
        assert "results" in body
        assert len(body["results"]) == 2

        # Assert: キャッシュメタデータで hit=False であること
        assert body["cache"]["hit"] is False

        # Assert: lookup_and_search が呼ばれていないこと（バイパス）
        # lookup_and_search はキャッシュ経由の検索で使われるが、
        # バイパス時は直接 Aurora に検索するため呼ばれない
        mock_generate_embedding.assert_called_once_with("テスト")

    @patch.object(_handler_mod, "lookup_and_search")
    @patch.object(_handler_mod, "_get_aurora_connection")
    @patch.object(_handler_mod, "generate_embedding")
    def test_bedrock_timeout_does_not_call_lookup_and_search(
        self,
        mock_generate_embedding: MagicMock,
        mock_get_aurora_connection: MagicMock,
        mock_lookup_and_search: MagicMock,
    ) -> None:
        """Bedrock タイムアウト時に lookup_and_search が呼ばれないこと."""
        # Arrange
        embedding_error = _handler_mod.EmbeddingError("Bedrock タイムアウト")
        mock_generate_embedding.side_effect = embedding_error

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("テスト結果", 0.1)]
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_aurora_connection.return_value = mock_connection

        # Act
        event: dict[str, object] = {"query": "テストクエリ"}
        response = semantic_cache_handler_fn(event, MagicMock())

        # Assert: lookup_and_search が呼ばれていないこと
        mock_lookup_and_search.assert_not_called()

        # Assert: レスポンスは正常
        assert response["statusCode"] == 200


# --- プロパティテスト: Lambda入力バリデーション ---


# semantic_cache_handler を取得
_semantic_cache_handler = _handler_mod.semantic_cache_handler


class TestProperty10LambdaInputValidation:
    """Property 10: Lambda入力バリデーション.

    任意の空文字列または1000文字を超過する文字列に対して、
    Lambda はバリデーションエラーレスポンス（statusCode 400）を返し、
    キャッシュおよび検索処理を実行しないこと。

    **Validates: Requirements 7.2**
    Feature: semantic-cache, Property 10: Lambda入力バリデーション
    """

    @given(
        query=st.just(""),
    )
    @settings(max_examples=100, deadline=None)
    @patch.object(_handler_mod, "generate_embedding")
    @patch.object(_handler_mod, "_get_aurora_connection")
    @patch.object(_handler_mod, "lookup_and_search")
    def test_empty_string_returns_400(
        self,
        mock_lookup: MagicMock,
        mock_aurora_conn: MagicMock,
        mock_embedding: MagicMock,
        query: str,
    ) -> None:
        """空文字列に対してバリデーションエラー（400）を返すこと.

        - statusCode が 400 であること
        - レスポンスボディに "error" が含まれること
        - generate_embedding が呼ばれないこと
        - _get_aurora_connection が呼ばれないこと
        - lookup_and_search が呼ばれないこと
        """
        event: dict[str, object] = {"query": query}
        response = _semantic_cache_handler(event, MagicMock())

        # statusCode 400 を返すこと
        assert response["statusCode"] == 400, (
            f"Expected statusCode 400 for empty string, "
            f"got {response['statusCode']}"
        )

        # レスポンスボディに "error" が含まれること
        body = json.loads(response["body"])
        assert "error" in body, (
            f"Expected 'error' in response body, got {body}"
        )

        # キャッシュおよび検索処理が実行されないこと
        mock_embedding.assert_not_called()
        mock_aurora_conn.assert_not_called()
        mock_lookup.assert_not_called()

    @given(
        query=st.text(min_size=1001, max_size=2000),
    )
    @settings(max_examples=100, deadline=None)
    @patch.object(_handler_mod, "generate_embedding")
    @patch.object(_handler_mod, "_get_aurora_connection")
    @patch.object(_handler_mod, "lookup_and_search")
    def test_over_1000_chars_returns_400(
        self,
        mock_lookup: MagicMock,
        mock_aurora_conn: MagicMock,
        mock_embedding: MagicMock,
        query: str,
    ) -> None:
        """1000文字を超過する文字列に対してバリデーションエラー（400）を返すこと.

        - statusCode が 400 であること
        - レスポンスボディに "error" が含まれること
        - generate_embedding が呼ばれないこと
        - _get_aurora_connection が呼ばれないこと
        - lookup_and_search が呼ばれないこと
        """
        event: dict[str, object] = {"query": query}
        response = _semantic_cache_handler(event, MagicMock())

        # statusCode 400 を返すこと
        assert response["statusCode"] == 400, (
            f"Expected statusCode 400 for query of length {len(query)}, "
            f"got {response['statusCode']}"
        )

        # レスポンスボディに "error" が含まれること
        body = json.loads(response["body"])
        assert "error" in body, (
            f"Expected 'error' in response body for query of "
            f"length {len(query)}, got {body}"
        )

        # キャッシュおよび検索処理が実行されないこと
        mock_embedding.assert_not_called()
        mock_aurora_conn.assert_not_called()
        mock_lookup.assert_not_called()


# --- プロパティテスト: 設定デフォルト値 ---
# Feature: semantic-cache, Property 11: 設定デフォルト値
# **Validates: Requirements 4.4, 8.4**


class TestConfigDefaultValuesProperty:
    """Property 11: 設定デフォルト値.

    任意の環境変数未設定状態に対して、SIMILARITY_THRESHOLD は 0.95、
    CACHE_TTL は 3600 がデフォルト値として使用されること。
    また、環境変数が設定されている場合はその値が使用されること。
    """

    @settings(max_examples=100)
    @given(st.just(None))
    def test_default_values_when_env_vars_unset(self, _: None) -> None:
        """環境変数未設定時にデフォルト値が使用されること."""
        env_backup_threshold = os.environ.pop("SIMILARITY_THRESHOLD", None)
        env_backup_ttl = os.environ.pop("CACHE_TTL", None)
        try:
            threshold, ttl = _get_config()
            assert threshold == 0.95, f"Expected 0.95, got {threshold}"
            assert ttl == 3600, f"Expected 3600, got {ttl}"
        finally:
            if env_backup_threshold is not None:
                os.environ["SIMILARITY_THRESHOLD"] = env_backup_threshold
            if env_backup_ttl is not None:
                os.environ["CACHE_TTL"] = env_backup_ttl

    @settings(max_examples=100)
    @given(
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ttl=st.integers(min_value=1, max_value=604800),
    )
    def test_env_var_values_used_when_set(self, threshold: float, ttl: int) -> None:
        """環境変数が設定されている場合、その値が使用されること."""
        env_backup_threshold = os.environ.get("SIMILARITY_THRESHOLD")
        env_backup_ttl = os.environ.get("CACHE_TTL")
        os.environ["SIMILARITY_THRESHOLD"] = str(threshold)
        os.environ["CACHE_TTL"] = str(ttl)
        try:
            result_threshold, result_ttl = _get_config()
            assert result_threshold == pytest.approx(threshold), (
                f"Expected {threshold}, got {result_threshold}"
            )
            assert result_ttl == ttl, f"Expected {ttl}, got {result_ttl}"
        finally:
            if env_backup_threshold is not None:
                os.environ["SIMILARITY_THRESHOLD"] = env_backup_threshold
            else:
                os.environ.pop("SIMILARITY_THRESHOLD", None)
            if env_backup_ttl is not None:
                os.environ["CACHE_TTL"] = env_backup_ttl
            else:
                os.environ.pop("CACHE_TTL", None)
