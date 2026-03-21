"""メトリクス算出のプロパティベーステスト.

Property 3: スループット算出の正確性
Property 6: フェーズ所要時間の合計一致
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st
from metrics import IngestionPhaseMetrics, calculate_throughput, calculate_total_duration


class TestProperty3ThroughputCalculationAccuracy:
    """Property 3: スループット算出の正確性.

    任意の正の整数 record_count と正の浮動小数点数 duration_seconds に対して、
    算出されるスループットは record_count / duration_seconds に等しいこと。

    **Validates: Requirements 4.8, 6.2**
    Feature: 03-vector-benchmark-execution, Property 3: スループット算出の正確性
    """

    @given(
        record_count=st.integers(min_value=0, max_value=10_000_000),
        duration_seconds=st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_throughput_equals_record_count_divided_by_duration(
        self, record_count: int, duration_seconds: float
    ) -> None:
        """スループットが record_count / duration_seconds と等しいこと."""
        result = calculate_throughput(record_count, duration_seconds)
        expected = record_count / duration_seconds
        assert math.isclose(result, expected, rel_tol=1e-9), (
            f"Expected {expected}, got {result}"
        )


PHASE_NAMES = ["index_drop", "data_insert", "index_create"]

phase_metrics_strategy = st.lists(
    st.builds(
        IngestionPhaseMetrics,
        phase=st.sampled_from(PHASE_NAMES),
        duration_seconds=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
        record_count=st.integers(min_value=0, max_value=10_000_000),
    ),
    min_size=1,
    max_size=10,
)


class TestProperty6PhaseDurationSumMatch:
    """Property 6: フェーズ所要時間の合計一致.

    任意の DatabaseIngestionResult に対して、phases 内の各 IngestionPhaseMetrics の
    duration_seconds の合計は total_duration_seconds と等しい（浮動小数点誤差を許容）こと。

    **Validates: Requirements 6.1**
    Feature: 03-vector-benchmark-execution, Property 6: フェーズ所要時間の合計一致
    """

    @given(phases=phase_metrics_strategy)
    @settings(max_examples=200)
    def test_total_duration_equals_sum_of_phase_durations(
        self, phases: list[IngestionPhaseMetrics]
    ) -> None:
        """calculate_total_duration の結果が各フェーズの duration_seconds の合計と一致すること."""
        result = calculate_total_duration(phases)
        expected = sum(p.duration_seconds for p in phases)
        assert math.isclose(result, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Expected {expected}, got {result}"
        )
