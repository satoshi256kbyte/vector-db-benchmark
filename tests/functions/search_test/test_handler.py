"""検索テスト Lambda ハンドラーのユニットテスト.

パラメータバリデーション、デフォルト値、エラーハンドリングを検証する。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


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
    for name in ["handler", "logic", "models", "vector_generator"]:
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
handler_fn = _handler_mod.handler


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
