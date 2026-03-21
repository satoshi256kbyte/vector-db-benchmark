"""プロパティベーステスト: ダミーベクトル生成とレスポンスモデル."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from models import DatabaseResult, VerifyResponse


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


# DatabaseResult を生成する Hypothesis ストラテジー
_database_result_strategy = st.builds(
    DatabaseResult,
    database=st.text(min_size=1, max_size=50),
    insert_count=st.integers(min_value=0, max_value=10000),
    search_result_count=st.integers(min_value=0, max_value=10000),
    success=st.booleans(),
    error_message=st.one_of(st.none(), st.text(min_size=1, max_size=200)),
)


@settings(max_examples=100)
@given(
    aurora=_database_result_strategy,
    opensearch=_database_result_strategy,
    s3vectors=_database_result_strategy,
    vector_dimension=st.integers(min_value=1, max_value=4096),
    total_vectors=st.integers(min_value=1, max_value=1000),
)
def test_verify_response_completeness_property(
    aurora: DatabaseResult,
    opensearch: DatabaseResult,
    s3vectors: DatabaseResult,
    vector_dimension: int,
    total_vectors: int,
) -> None:
    """Feature: 01-vector-db-benchmark, Property 3: レスポンスモデルの完全性.

    VerifyResponse は aurora, opensearch, s3vectors の3つの DatabaseResult フィールドを
    持たなければならない。

    Validates: Requirements 5.11
    """
    response = VerifyResponse(
        aurora=aurora,
        opensearch=opensearch,
        s3vectors=s3vectors,
        vector_dimension=vector_dimension,
        total_vectors=total_vectors,
    )

    # 3つの DatabaseResult フィールドが存在すること
    assert hasattr(response, "aurora")
    assert hasattr(response, "opensearch")
    assert hasattr(response, "s3vectors")

    # 各フィールドが DatabaseResult インスタンスであること
    assert isinstance(response.aurora, DatabaseResult)
    assert isinstance(response.opensearch, DatabaseResult)
    assert isinstance(response.s3vectors, DatabaseResult)

    # to_dict() で全フィールドがシリアライズされること
    response_dict = response.to_dict()
    assert "aurora" in response_dict
    assert "opensearch" in response_dict
    assert "s3vectors" in response_dict
    assert "vector_dimension" in response_dict
    assert "total_vectors" in response_dict
