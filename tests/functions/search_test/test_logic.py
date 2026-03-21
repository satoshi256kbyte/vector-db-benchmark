"""検索テスト logic.py のプロパティベーステスト・ユニットテスト.

Property 5: レイテンシ統計算出の正確性
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st


def _passthrough_decorator(func=None, **kwargs):  # noqa: ANN001, ANN003
    """Powertools デコレータのパススルーモック."""
    if func is not None:
        return func
    return _passthrough_decorator


def _import_search_test_logic() -> ModuleType:
    """functions/search-test/logic.py を外部依存モック付きでインポートする.

    pythonpath に functions/vector-verify が先に登録されているため、
    functions/search-test を一時的に優先してインポートする。
    aws_lambda_powertools 等の外部依存はモックで差し替える。
    """
    search_test_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "functions" / "search-test")

    # 外部依存のモック設定
    mock_powertools = MagicMock()
    mock_powertools.Logger.return_value = MagicMock()
    mock_powertools.Tracer.return_value = MagicMock()

    ext_mocks: dict[str, MagicMock] = {
        "psycopg2": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "opensearchpy": MagicMock(),
        "requests_aws4auth": MagicMock(),
        "aws_lambda_powertools": mock_powertools,
    }

    # 現在の sys.path と sys.modules を保存
    original_path = sys.path[:]
    saved_logic = sys.modules.pop("logic", None)
    saved_models = sys.modules.pop("models", None)
    saved_ext: dict[str, object] = {}
    for mod_name, mock in ext_mocks.items():
        saved_ext[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock

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
        # インポートした search-test の logic/models をキャッシュから退避
        sys.modules.pop("logic", None)
        sys.modules.pop("models", None)
        # 元のモジュールキャッシュを復元
        if saved_logic is not None:
            sys.modules["logic"] = saved_logic
        if saved_models is not None:
            sys.modules["models"] = saved_models
        # 外部依存モックを復元
        for mod_name in ext_mocks:
            if saved_ext[mod_name] is not None:
                sys.modules[mod_name] = saved_ext[mod_name]  # type: ignore[assignment]
            else:
                sys.modules.pop(mod_name, None)


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



# --- 追加: 検索ロジックのユニットテスト (Task 6.3) ---
from unittest.mock import MagicMock

import pytest as _pytest  # noqa: E402

search_aurora = _logic.search_aurora
search_opensearch = _logic.search_opensearch
search_s3vectors = _logic.search_s3vectors
build_comparison_table = _logic.build_comparison_table
_create_failure_result = _logic._create_failure_result


def _make_success_result(database: str) -> object:
    """テスト用の成功 DatabaseSearchResult を生成する."""
    return _logic.DatabaseSearchResult(
        database=database,
        latency=_logic.LatencyStats(avg_ms=10.0, p50_ms=9.0, p95_ms=15.0, p99_ms=18.0, min_ms=5.0, max_ms=20.0),
        throughput_qps=100.0,
        search_count=10,
        top_k=5,
        success=True,
    )


class TestSearchAurora:
    """search_aurora のユニットテスト."""

    def test_success_all_queries(self) -> None:
        """全クエリ成功時に正しい結果を返すこと."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "doc", 0.1)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        vectors = [[0.1] * 10, [0.2] * 10, [0.3] * 10]
        result = search_aurora(mock_conn, vectors, 5)

        assert result.database == "aurora_pgvector"
        assert result.success is True
        assert result.search_count == 3
        assert result.top_k == 5
        assert result.latency.min_ms >= 0

    def test_all_queries_fail(self) -> None:
        """全クエリ失敗時に failure result を返すこと."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("query error")
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        vectors = [[0.1] * 10]
        result = search_aurora(mock_conn, vectors, 5)

        assert result.success is False
        assert result.error_message == "All queries failed"

    def test_partial_failure(self) -> None:
        """一部クエリ失敗時に成功分のみカウントされること."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("query error")

        mock_cursor.execute.side_effect = side_effect
        mock_cursor.fetchall.return_value = [(1, "doc", 0.1)]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        vectors = [[0.1] * 10, [0.2] * 10, [0.3] * 10]
        result = search_aurora(mock_conn, vectors, 5)

        assert result.success is True
        assert result.search_count == 2  # 3 - 1 failed


class TestSearchOpensearch:
    """search_opensearch のユニットテスト."""

    def test_success_all_queries(self) -> None:
        """全クエリ成功時に正しい結果を返すこと."""
        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"hits": []}}

        vectors = [[0.1] * 10, [0.2] * 10]
        result = search_opensearch(mock_client, vectors, 5)

        assert result.database == "opensearch"
        assert result.success is True
        assert result.search_count == 2

    def test_all_queries_fail(self) -> None:
        """全クエリ失敗時に failure result を返すこと."""
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("connection error")

        vectors = [[0.1] * 10]
        result = search_opensearch(mock_client, vectors, 5)

        assert result.success is False
        assert result.error_message == "All queries failed"


class TestSearchS3vectors:
    """search_s3vectors のユニットテスト."""

    def test_success_all_queries(self) -> None:
        """全クエリ成功時に正しい結果を返すこと."""
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {"vectors": []}

        vectors = [[0.1] * 10, [0.2] * 10]
        result = search_s3vectors(mock_client, "bucket", "index", vectors, 5)

        assert result.database == "s3vectors"
        assert result.success is True
        assert result.search_count == 2

    def test_all_queries_fail(self) -> None:
        """全クエリ失敗時に failure result を返すこと."""
        mock_client = MagicMock()
        mock_client.query_vectors.side_effect = RuntimeError("api error")

        vectors = [[0.1] * 10]
        result = search_s3vectors(mock_client, "bucket", "index", vectors, 5)

        assert result.success is False


class TestBuildComparisonTable:
    """build_comparison_table のユニットテスト."""

    def test_generates_correct_metrics(self) -> None:
        """7つのメトリクス行が生成されること."""
        aurora = _make_success_result("aurora_pgvector")
        opensearch = _make_success_result("opensearch")
        s3vectors = _make_success_result("s3vectors")

        table = build_comparison_table(aurora, opensearch, s3vectors)  # type: ignore[arg-type]

        assert len(table) == 7
        metric_names = [row["metric"] for row in table]
        assert "avg_ms" in metric_names
        assert "throughput_qps" in metric_names

    def test_failure_shows_na(self) -> None:
        """失敗DBのメトリクスが N/A になること."""
        aurora = _create_failure_result("aurora_pgvector", 10, 5, "error")
        opensearch = _make_success_result("opensearch")
        s3vectors = _make_success_result("s3vectors")

        table = build_comparison_table(aurora, opensearch, s3vectors)  # type: ignore[arg-type]

        for row in table:
            assert row["aurora_pgvector"] == "N/A"


class TestCreateFailureResult:
    """_create_failure_result のユニットテスト."""

    def test_returns_failure(self) -> None:
        """失敗結果が正しく生成されること."""
        result = _create_failure_result("test_db", 10, 5, "test error")
        assert result.success is False
        assert result.database == "test_db"
        assert result.error_message == "test error"
        assert result.latency.avg_ms == 0

    def test_empty_stats(self) -> None:
        """レイテンシ統計が全て0であること."""
        result = _create_failure_result("db", 1, 1, "err")
        assert result.latency.p50_ms == 0
        assert result.latency.p95_ms == 0
        assert result.throughput_qps == 0.0


class TestCalculateLatencyStatsEdgeCases:
    """calculate_latency_stats のエッジケーステスト."""

    def test_single_element(self) -> None:
        """要素1つのリストで全統計値が同一になること."""
        stats = calculate_latency_stats([42.0])
        assert stats.avg_ms == 42.0
        assert stats.min_ms == 42.0
        assert stats.max_ms == 42.0
        assert stats.p50_ms == 42.0

    def test_empty_list_raises(self) -> None:
        """空リストで ValueError が発生すること."""
        with _pytest.raises(ValueError, match="must not be empty"):
            calculate_latency_stats([])

    def test_two_elements(self) -> None:
        """要素2つのリストで正しい統計値が返ること."""
        stats = calculate_latency_stats([10.0, 20.0])
        assert stats.min_ms == 10.0
        assert stats.max_ms == 20.0
        assert stats.avg_ms == 15.0
