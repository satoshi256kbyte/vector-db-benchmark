"""設定管理モジュールのテスト."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

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
DEFAULT_MEMORYDB_PORT = _config_module.DEFAULT_MEMORYDB_PORT
DEFAULT_SIMILARITY_THRESHOLD = _config_module.DEFAULT_SIMILARITY_THRESHOLD
DEFAULT_CACHE_TTL = _config_module.DEFAULT_CACHE_TTL


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
