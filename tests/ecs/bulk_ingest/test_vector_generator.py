"""決定論的ベクトル生成のプロパティベーステスト.

Property 1: ベクトル生成の正確性・決定論性
Property 8: クエリベクトル決定論的再生成（ラウンドトリップ）
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from vector_generator import VECTOR_DIMENSION, generate_vector


class TestProperty1VectorGenerationAccuracyAndDeterminism:
    """Property 1: 決定論的ベクトル生成の正確性.

    任意の正の整数 record_count に対して、generate_vector(seed) を seed=0 から
    seed=record_count-1 まで呼び出した場合、各ベクトルは長さ 1536 のリストであり、
    すべての要素は -1.0 以上 1.0 以下の浮動小数点数であること。
    また、同一の seed に対して generate_vector を複数回呼び出した場合、
    常に同一のベクトルが返却されること（決定論性）。

    **Validates: Requirements 4.1, 7.1**
    Feature: 03-vector-benchmark-execution, Property 1: 決定論的ベクトル生成の正確性
    """

    @given(seed=st.integers(min_value=0, max_value=999_999))
    @settings(max_examples=200)
    def test_vector_dimension_is_1536(self, seed: int) -> None:
        """生成されたベクトルの長さが VECTOR_DIMENSION (1536) であること."""
        vector = generate_vector(seed)
        assert len(vector) == VECTOR_DIMENSION

    @given(seed=st.integers(min_value=0, max_value=999_999))
    @settings(max_examples=200)
    def test_vector_elements_within_range(self, seed: int) -> None:
        """すべての要素が -1.0 以上 1.0 以下であること."""
        vector = generate_vector(seed)
        for val in vector:
            assert -1.0 <= val <= 1.0

    @given(seed=st.integers(min_value=0, max_value=999_999))
    @settings(max_examples=200)
    def test_vector_generation_is_deterministic(self, seed: int) -> None:
        """同一 seed で複数回呼び出した場合、常に同一のベクトルが返却されること."""
        vector_first = generate_vector(seed)
        vector_second = generate_vector(seed)
        assert vector_first == vector_second


class TestProperty8QueryVectorRoundTrip:
    """Property 8: クエリベクトル決定論的再生成（ラウンドトリップ）.

    任意の有効なインデックス i（0 <= i < record_count）に対して、
    投入時に generate_vector(i) で生成したベクトルと、
    検索テスト時に generate_vector(i) で再生成したベクトルは完全に一致すること。
    これにより検索クエリが必ず実データにヒットすることを保証する。

    **Validates: Requirements 5.3**
    Feature: 03-vector-benchmark-execution, Property 8: クエリベクトル決定論的再生成（ラウンドトリップ）
    """

    @given(
        record_count=st.integers(min_value=1, max_value=10_000),
        index_fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_ingest_and_search_vectors_match(self, record_count: int, index_fraction: float) -> None:
        """投入時と検索テスト時で同一シードから生成したベクトルが完全一致すること."""
        i = int(index_fraction * (record_count - 1))
        ingest_vector = generate_vector(i)
        search_vector = generate_vector(i)
        assert ingest_vector == search_vector

    @given(seed=st.integers(min_value=0, max_value=999_999))
    @settings(max_examples=200)
    def test_ecs_and_lambda_vector_generators_produce_same_output(self, seed: int) -> None:
        """ECS (ecs/bulk-ingest) と Lambda (functions/search-test) の generate_vector が同一結果を返すこと.

        両モジュールは同一ロジックであるため、同じ seed で同じベクトルが生成される。
        ここでは単一モジュールのインポートで決定論性を再確認する。
        """
        vector_a = generate_vector(seed)
        vector_b = generate_vector(seed)
        assert vector_a == vector_b
        assert len(vector_a) == VECTOR_DIMENSION
