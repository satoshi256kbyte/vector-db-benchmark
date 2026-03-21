"""プロパティベーステスト: ダミーベクトル生成とレスポンスモデル."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from models import DatabaseResult


def _import_generate_dummy_vectors():
    """logic モジュールから generate_dummy_vectors のみを安全にインポートする.

    logic.py は psycopg2, opensearchpy 等の Lambda 実行時依存を持つため、
    テスト環境ではそれらをモックしてインポートする。
    """
    stubs = {
        "psycopg2": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "opensearchpy": MagicMock(),
        "requests_aws4auth": MagicMock(),
        "aws_lambda_powertools": MagicMock(),
    }
    saved = {}
    for mod_name, mock in stubs.items():
        saved[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

    try:
        if "logic" in sys.modules:
            del sys.modules["logic"]
        import logic

        return logic.generate_dummy_vectors
    finally:
        for mod_name, original in saved.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original


generate_dummy_vectors = _import_generate_dummy_vectors()


@settings(max_examples=100)
@given(
    count=st.integers(min_value=1, max_value=100),
    dimension=st.integers(min_value=1, max_value=2048),
)
def test_generate_dummy_vectors_property(count: int, dimension: int) -> None:
    """Feature: 01-vector-db-benchmark, Property 2: ダミーベクトル生成の正確性.

    Validates: Requirements 5.3
    """
    vectors = generate_dummy_vectors(count, dimension)
    assert len(vectors) == count
    for v in vectors:
        assert len(v) == dimension
        assert all(-1.0 <= x <= 1.0 for x in v)


@settings(max_examples=100)
@given(
    database=st.text(min_size=1, max_size=50),
    insert_count=st.integers(min_value=0, max_value=10000),
    search_result_count=st.integers(min_value=0, max_value=10000),
    success=st.booleans(),
    error_message=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
)
def test_database_result_completeness_property(
    database: str,
    insert_count: int,
    search_result_count: int,
    success: bool,
    error_message: str | None,
) -> None:
    """Feature: 01-vector-db-benchmark, Property 3: レスポンスモデルの完全性.

    Validates: Requirements 5.9
    """
    if not success and error_message is None:
        error_message = "unknown error"

    result = DatabaseResult(
        database=database,
        insert_count=insert_count,
        search_result_count=search_result_count,
        success=success,
        error_message=error_message,
    )

    assert hasattr(result, "database")
    assert hasattr(result, "insert_count")
    assert hasattr(result, "search_result_count")
    assert hasattr(result, "success")

    if not result.success:
        assert result.error_message is not None
