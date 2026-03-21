"""レイテンシ統計算出のプロパティベーステスト.

Property 5: レイテンシ統計算出の正確性
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from types import ModuleType

from hypothesis import given, settings
from hypothesis import strategies as st


def _import_search_test_logic() -> ModuleType:
    """functions/search-test/logic.py を明示的にインポートする.

    pythonpath に functions/vector-verify が先に登録されているため、
    functions/search-test を一時的に優先してインポートする。
    """
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    # 現在の sys.path と sys.modules を保存
    original_path = sys.path[:]
    saved_logic = sys.modules.pop("logic", None)
    saved_models = sys.modules.pop("models", None)

    try:
        # functions/search-test を先頭に挿入
        if search_test_dir in sys.path:
            sys.path.remove(search_test_dir)
        sys.path.insert(0, search_test_dir)

        module = importlib.import_module("logic")
        return module
    finally:
        # sys.path を復元
        sys.path[:] = original_path
        # インポートした search-test の logic/models はキャッシュに残す（別名で退避）
        _search_logic = sys.modules.pop("logic", None)
        _search_models = sys.modules.pop("models", None)
        # 元のモジュールキャッシュを復元
        if saved_logic is not None:
            sys.modules["logic"] = saved_logic
        if saved_models is not None:
            sys.modules["models"] = saved_models


# モジュールレベルでインポート（他テストモジュールへの影響を回避）
_logic = _import_search_test_logic()
calculate_latency_stats = _logic.calculate_latency_stats

positive_float_strategy = st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False)

latencies_strategy = st.lists(positive_float_strategy, min_size=1, max_size=500)


class TestProperty5LatencyStatsAccuracy:
    """Property 5: レイテンシ統計算出の正確性.

    任意の正の浮動小数点数のリスト（長さ1以上）に対して、
    calculate_latency_stats が返す統計値は以下を満たすこと:
    P50 は中央値、P95 は 95 パーセンタイル値、P99 は 99 パーセンタイル値であり、
    min <= P50 <= P95 <= P99 <= max かつ min <= avg <= max が成立すること。

    **Validates: Requirements 5.5, 6.3**
    Feature: 03-vector-benchmark-execution, Property 5: レイテンシ統計算出の正確性
    """

    @given(latencies=latencies_strategy)
    @settings(max_examples=200)
    def test_percentile_ordering(self, latencies: list[float]) -> None:
        """min <= P50 <= P95 <= P99 <= max が成立すること."""
        stats = calculate_latency_stats(latencies)
        assert stats.min_ms <= stats.p50_ms, f"min ({stats.min_ms}) > P50 ({stats.p50_ms})"
        assert stats.p50_ms <= stats.p95_ms, f"P50 ({stats.p50_ms}) > P95 ({stats.p95_ms})"
        assert stats.p95_ms <= stats.p99_ms, f"P95 ({stats.p95_ms}) > P99 ({stats.p99_ms})"
        assert stats.p99_ms <= stats.max_ms, f"P99 ({stats.p99_ms}) > max ({stats.max_ms})"

    @given(latencies=latencies_strategy)
    @settings(max_examples=200)
    def test_avg_within_min_max(self, latencies: list[float]) -> None:
        """min <= avg <= max が成立すること（浮動小数点誤差を許容）."""
        stats = calculate_latency_stats(latencies)
        assert stats.min_ms <= stats.avg_ms or math.isclose(stats.min_ms, stats.avg_ms, rel_tol=1e-9), (
            f"min ({stats.min_ms}) > avg ({stats.avg_ms})"
        )
        assert stats.avg_ms <= stats.max_ms or math.isclose(stats.avg_ms, stats.max_ms, rel_tol=1e-9), (
            f"avg ({stats.avg_ms}) > max ({stats.max_ms})"
        )

    @given(latencies=latencies_strategy)
    @settings(max_examples=200)
    def test_min_and_max_match_sorted_array(self, latencies: list[float]) -> None:
        """min は最小値、max は最大値と一致すること."""
        stats = calculate_latency_stats(latencies)
        arr = sorted(latencies)
        assert stats.min_ms == arr[0], f"min mismatch: {stats.min_ms} != {arr[0]}"
        assert stats.max_ms == arr[-1], f"max mismatch: {stats.max_ms} != {arr[-1]}"

    @given(latencies=latencies_strategy)
    @settings(max_examples=200)
    def test_p50_is_median(self, latencies: list[float]) -> None:
        """P50 がソート済み配列の中央値と一致すること."""
        stats = calculate_latency_stats(latencies)
        arr = sorted(latencies)
        n = len(arr)
        expected_p50 = arr[n // 2]
        assert stats.p50_ms == expected_p50, f"P50 mismatch: {stats.p50_ms} != {expected_p50}"

    @given(latencies=latencies_strategy)
    @settings(max_examples=200)
    def test_p95_and_p99_match_index_based_calculation(self, latencies: list[float]) -> None:
        """P95 と P99 がインデックスベースの算出値と一致すること."""
        stats = calculate_latency_stats(latencies)
        arr = sorted(latencies)
        n = len(arr)
        expected_p95 = arr[int(n * 0.95)]
        expected_p99 = arr[int(n * 0.99)]
        assert stats.p95_ms == expected_p95, f"P95 mismatch: {stats.p95_ms} != {expected_p95}"
        assert stats.p99_ms == expected_p99, f"P99 mismatch: {stats.p99_ms} != {expected_p99}"
