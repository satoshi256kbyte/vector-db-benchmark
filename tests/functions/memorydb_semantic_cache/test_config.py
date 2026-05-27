"""設定管理モジュールのテスト."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis import given, settings
from hypothesis import strategies as st

# functions/memorydb-semantic-cache/config.py を直接ロード（sys.path 汚染なし）
_FUNC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "functions" / "memorydb-semantic-cache"
_CONFIG_PATH = _FUNC_DIR / "config.py"


def _load_config_module() -> ModuleType:
    """config モジュールを aws_lambda_powertools モック付きでロードする."""
    mock_powertools = MagicMock()
    mock_logger = MagicMock()
    mock_powertools.Logger.return_value = mock_logger

    spec = importlib.util.spec_from_file_location("memorydb_config", _CONFIG_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    # aws_lambda_powertools をモックに差し替えてからロード
    import sys

    original_modules = sys.modules.copy()
    sys.modules["aws_lambda_powertools"] = mock_powertools
    try:
        spec.loader.exec_module(module)
    finally:
        # モジュールキャッシュを元に戻す（aws_lambda_powertools のみ）
        if "aws_lambda_powertools" not in original_modules:
            sys.modules.pop("aws_lambda_powertools", None)
        else:
            sys.modules["aws_lambda_powertools"] = original_modules["aws_lambda_powertools"]

    return module


_config_module = _load_config_module()
CacheConfig = _config_module.CacheConfig
load_config = _config_module.load_config
_parse_cache_ttl = _config_module._parse_cache_ttl
DEFAULT_MEMORYDB_PORT = _config_module.DEFAULT_MEMORYDB_PORT
DEFAULT_SIMILARITY_THRESHOLD = _config_module.DEFAULT_SIMILARITY_THRESHOLD
DEFAULT_CACHE_TTL = _config_module.DEFAULT_CACHE_TTL
MIN_CACHE_TTL = _config_module.MIN_CACHE_TTL
MAX_CACHE_TTL = _config_module.MAX_CACHE_TTL


class TestLoadConfig:
    """load_config() のテスト."""

    def test_valid_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """全ての環境変数が有効な場合、正しい設定が返される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "my-cluster.abc123.memorydb.ap-northeast-1.amazonaws.com")
        monkeypatch.setenv("MEMORYDB_PORT", "6380")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.85")
        monkeypatch.setenv("CACHE_TTL", "7200")

        config = load_config()

        assert config.memorydb_endpoint == "my-cluster.abc123.memorydb.ap-northeast-1.amazonaws.com"
        assert config.memorydb_port == 6380
        assert config.similarity_threshold == 0.85
        assert config.cache_ttl == 7200

    def test_missing_endpoint_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MEMORYDB_ENDPOINT が未設定の場合、ValueError が発生する."""
        monkeypatch.delenv("MEMORYDB_ENDPOINT", raising=False)

        with pytest.raises(ValueError, match="MEMORYDB_ENDPOINT"):
            load_config()

    def test_empty_endpoint_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MEMORYDB_ENDPOINT が空文字の場合、ValueError が発生する."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "")

        with pytest.raises(ValueError, match="MEMORYDB_ENDPOINT"):
            load_config()

    def test_defaults_when_optional_env_vars_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """オプション環境変数が未設定の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.delenv("MEMORYDB_PORT", raising=False)
        monkeypatch.delenv("SIMILARITY_THRESHOLD", raising=False)
        monkeypatch.delenv("CACHE_TTL", raising=False)

        config = load_config()

        assert config.memorydb_port == DEFAULT_MEMORYDB_PORT
        assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD
        assert config.cache_ttl == DEFAULT_CACHE_TTL


class TestSimilarityThresholdValidation:
    """SIMILARITY_THRESHOLD バリデーションのテスト."""

    def test_valid_boundary_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0.0 は有効な値."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.0")

        config = load_config()
        assert config.similarity_threshold == 0.0

    def test_valid_boundary_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1.0 は有効な値."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "1.0")

        config = load_config()
        assert config.similarity_threshold == 1.0

    def test_negative_value_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """負の値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "-0.1")

        config = load_config()
        assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD

    def test_over_one_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1.0 を超える値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "1.1")

        config = load_config()
        assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD

    def test_non_numeric_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非数値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("SIMILARITY_THRESHOLD", "abc")

        config = load_config()
        assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD


class TestCacheTtlValidation:
    """CACHE_TTL バリデーションのテスト."""

    def test_valid_boundary_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1 は有効な最小値."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "1")

        config = load_config()
        assert config.cache_ttl == 1

    def test_valid_boundary_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """604800 は有効な最大値."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "604800")

        config = load_config()
        assert config.cache_ttl == 604800

    def test_zero_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0 の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "0")

        config = load_config()
        assert config.cache_ttl == DEFAULT_CACHE_TTL

    def test_negative_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """負の値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "-1")

        config = load_config()
        assert config.cache_ttl == DEFAULT_CACHE_TTL

    def test_over_max_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """604800 を超える値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "604801")

        config = load_config()
        assert config.cache_ttl == DEFAULT_CACHE_TTL

    def test_float_value_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """浮動小数点数の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "3.14")

        config = load_config()
        assert config.cache_ttl == DEFAULT_CACHE_TTL

    def test_non_numeric_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非数値の場合、デフォルト値が使用される."""
        monkeypatch.setenv("MEMORYDB_ENDPOINT", "test-endpoint")
        monkeypatch.setenv("CACHE_TTL", "abc")

        config = load_config()
        assert config.cache_ttl == DEFAULT_CACHE_TTL


class TestCacheConfigDataclass:
    """CacheConfig dataclass のテスト."""

    def test_dataclass_fields(self) -> None:
        """CacheConfig が正しいフィールドを持つ."""
        config = CacheConfig(
            memorydb_endpoint="test-endpoint",
            memorydb_port=6379,
            similarity_threshold=0.95,
            cache_ttl=3600,
        )

        assert config.memorydb_endpoint == "test-endpoint"
        assert config.memorydb_port == 6379
        assert config.similarity_threshold == 0.95
        assert config.cache_ttl == 3600


# ---------------------------------------------------------------------------
# Property 4: Similarity_Threshold 設定バリデーション
# Feature: 09-semantic-cache-memorydb, Property 4: Similarity_Threshold 設定バリデーション
# Validates: Requirements 4.4, 4.5, 8.6
# ---------------------------------------------------------------------------

# 有効な類似度閾値: 0.0〜1.0 の浮動小数点数
_valid_threshold_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# 範囲外の浮動小数点数（< 0.0 または > 1.0）
_out_of_range_threshold_strategy = st.one_of(
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
)

# 非数値文字列（float() で変換できない文字列）
_non_numeric_strategy = st.text(
    alphabet=st.characters(
        categories=("L", "N", "P", "S", "Z"),
        exclude_characters="0123456789.+-eE",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: _is_non_numeric(s))


def _is_non_numeric(s: str) -> bool:
    """文字列が float に変換できないことを確認する."""
    try:
        float(s)
        return False
    except ValueError:
        return True


class TestSimilarityThresholdProperty:
    """Property 4: Similarity_Threshold 設定バリデーション.

    任意の環境変数値に対して、0.0〜1.0 の範囲内の有効な浮動小数点数であれば
    当該値が使用され、範囲外の値または非数値の場合はデフォルト値 0.95 が使用されること。

    **Validates: Requirements 4.4, 4.5, 8.6**
    """

    @given(threshold=_valid_threshold_strategy)
    @settings(max_examples=100)
    def test_valid_threshold_is_used_as_is(self, threshold: float) -> None:
        """任意の有効な閾値（0.0〜1.0）がそのまま使用されること.

        Feature: 09-semantic-cache-memorydb, Property 4: Similarity_Threshold 設定バリデーション
        Validates: Requirements 4.4, 4.5, 8.6
        """
        import os

        original_endpoint = os.environ.get("MEMORYDB_ENDPOINT")
        original_threshold = os.environ.get("SIMILARITY_THRESHOLD")
        try:
            os.environ["MEMORYDB_ENDPOINT"] = "test-endpoint"
            os.environ["SIMILARITY_THRESHOLD"] = str(threshold)

            config = load_config()
            assert config.similarity_threshold == threshold
        finally:
            if original_endpoint is None:
                os.environ.pop("MEMORYDB_ENDPOINT", None)
            else:
                os.environ["MEMORYDB_ENDPOINT"] = original_endpoint
            if original_threshold is None:
                os.environ.pop("SIMILARITY_THRESHOLD", None)
            else:
                os.environ["SIMILARITY_THRESHOLD"] = original_threshold

    @given(threshold=_out_of_range_threshold_strategy)
    @settings(max_examples=100)
    def test_out_of_range_threshold_uses_default(self, threshold: float) -> None:
        """任意の範囲外の値に対してデフォルト値 0.95 が使用されること.

        Feature: 09-semantic-cache-memorydb, Property 4: Similarity_Threshold 設定バリデーション
        Validates: Requirements 4.4, 4.5, 8.6
        """
        import os

        original_endpoint = os.environ.get("MEMORYDB_ENDPOINT")
        original_threshold = os.environ.get("SIMILARITY_THRESHOLD")
        try:
            os.environ["MEMORYDB_ENDPOINT"] = "test-endpoint"
            os.environ["SIMILARITY_THRESHOLD"] = str(threshold)

            config = load_config()
            assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD
        finally:
            if original_endpoint is None:
                os.environ.pop("MEMORYDB_ENDPOINT", None)
            else:
                os.environ["MEMORYDB_ENDPOINT"] = original_endpoint
            if original_threshold is None:
                os.environ.pop("SIMILARITY_THRESHOLD", None)
            else:
                os.environ["SIMILARITY_THRESHOLD"] = original_threshold

    @given(value=_non_numeric_strategy)
    @settings(max_examples=100)
    def test_non_numeric_value_uses_default(self, value: str) -> None:
        """任意の非数値文字列に対してデフォルト値 0.95 が使用されること.

        Feature: 09-semantic-cache-memorydb, Property 4: Similarity_Threshold 設定バリデーション
        Validates: Requirements 4.4, 4.5, 8.6
        """
        import os

        original_endpoint = os.environ.get("MEMORYDB_ENDPOINT")
        original_threshold = os.environ.get("SIMILARITY_THRESHOLD")
        try:
            os.environ["MEMORYDB_ENDPOINT"] = "test-endpoint"
            os.environ["SIMILARITY_THRESHOLD"] = value

            config = load_config()
            assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD
        finally:
            if original_endpoint is None:
                os.environ.pop("MEMORYDB_ENDPOINT", None)
            else:
                os.environ["MEMORYDB_ENDPOINT"] = original_endpoint
            if original_threshold is None:
                os.environ.pop("SIMILARITY_THRESHOLD", None)
            else:
                os.environ["SIMILARITY_THRESHOLD"] = original_threshold


# ---------------------------------------------------------------------------
# Property 5: CACHE_TTL 設定バリデーション
# Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
# Validates: Requirements 5.4, 6.1, 6.2, 8.6
# ---------------------------------------------------------------------------

# 非整数文字列（int() で変換できない文字列）
_non_integer_strategy = st.text(
    alphabet=st.characters(exclude_characters="\x00"),
    min_size=1,
    max_size=50,
).filter(lambda s: _is_non_integer(s))


def _is_non_integer(s: str) -> bool:
    """文字列が int に変換できないことを確認する."""
    try:
        int(s)
        return False
    except ValueError:
        return True


class TestCacheTtlPropertyValidation:
    """Property 5: CACHE_TTL 設定バリデーション.

    任意の環境変数値に対して、1〜604800 の範囲内の有効な正の整数であれば
    当該値が使用され、範囲外の値または整数として解釈できない値の場合は
    デフォルト値 3600 が使用されること。

    **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
    """

    @given(ttl=st.integers(min_value=MIN_CACHE_TTL, max_value=MAX_CACHE_TTL))
    @settings(max_examples=100)
    def test_valid_ttl_is_used_as_is(self, ttl: int) -> None:
        """有効範囲内の正の整数は、そのまま CACHE_TTL として使用される.

        Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
        **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
        """
        import os

        original = os.environ.get("CACHE_TTL")
        try:
            os.environ["CACHE_TTL"] = str(ttl)
            result = _parse_cache_ttl()
            assert result == ttl
        finally:
            if original is None:
                os.environ.pop("CACHE_TTL", None)
            else:
                os.environ["CACHE_TTL"] = original

    @given(ttl=st.integers(max_value=0))
    @settings(max_examples=100)
    def test_zero_or_negative_uses_default(self, ttl: int) -> None:
        """0 以下の整数はデフォルト値 3600 が使用される.

        Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
        **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
        """
        import os

        original = os.environ.get("CACHE_TTL")
        try:
            os.environ["CACHE_TTL"] = str(ttl)
            result = _parse_cache_ttl()
            assert result == DEFAULT_CACHE_TTL
        finally:
            if original is None:
                os.environ.pop("CACHE_TTL", None)
            else:
                os.environ["CACHE_TTL"] = original

    @given(ttl=st.integers(min_value=MAX_CACHE_TTL + 1))
    @settings(max_examples=100)
    def test_over_max_uses_default(self, ttl: int) -> None:
        """604800 を超える整数はデフォルト値 3600 が使用される.

        Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
        **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
        """
        import os

        original = os.environ.get("CACHE_TTL")
        try:
            os.environ["CACHE_TTL"] = str(ttl)
            result = _parse_cache_ttl()
            assert result == DEFAULT_CACHE_TTL
        finally:
            if original is None:
                os.environ.pop("CACHE_TTL", None)
            else:
                os.environ["CACHE_TTL"] = original

    @given(
        value=st.floats(allow_nan=False, allow_infinity=False).filter(
            lambda x: x != int(x) if x == x else True
        )
    )
    @settings(max_examples=100)
    def test_float_values_use_default(self, value: float) -> None:
        """浮動小数点数（整数でない値）はデフォルト値 3600 が使用される.

        Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
        **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
        """
        import os

        original = os.environ.get("CACHE_TTL")
        try:
            os.environ["CACHE_TTL"] = str(value)
            result = _parse_cache_ttl()
            assert result == DEFAULT_CACHE_TTL
        finally:
            if original is None:
                os.environ.pop("CACHE_TTL", None)
            else:
                os.environ["CACHE_TTL"] = original

    @given(value=_non_integer_strategy)
    @settings(max_examples=100)
    def test_non_numeric_strings_use_default(self, value: str) -> None:
        """整数として解釈できない文字列はデフォルト値 3600 が使用される.

        Feature: 09-semantic-cache-memorydb, Property 5: CACHE_TTL 設定バリデーション
        **Validates: Requirements 5.4, 6.1, 6.2, 8.6**
        """
        import os

        original = os.environ.get("CACHE_TTL")
        try:
            os.environ["CACHE_TTL"] = value
            result = _parse_cache_ttl()
            assert result == DEFAULT_CACHE_TTL
        finally:
            if original is None:
                os.environ.pop("CACHE_TTL", None)
            else:
                os.environ["CACHE_TTL"] = original
