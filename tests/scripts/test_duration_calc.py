"""処理時間算出のプロパティベーステスト.

Property 3: 処理時間算出の正確性
任意の 2つの ISO 8601 形式タイムスタンプ（終了時刻 >= 開始時刻）に対して、
算出される処理時間（秒）は終了時刻と開始時刻の差分に等しいこと。

Feature: 04-benchmark-shell-script, Property 3: 処理時間算出の正確性
"""

from __future__ import annotations

import calendar
import subprocess
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st


def iso8601_timestamps() -> st.SearchStrategy[tuple[str, str]]:
    """終了時刻 >= 開始時刻 となる ISO 8601 タイムスタンプペアを生成する.

    Returns:
        (start_time, end_time) のタプルを生成する Hypothesis ストラテジ。
    """
    # 1970-01-02 ~ 2099-12-31 の範囲で epoch 秒を生成
    # date コマンドの互換性のため 0 以下は避ける
    epoch_strategy = st.integers(min_value=86400, max_value=4102444800)

    return st.tuples(epoch_strategy, epoch_strategy).map(
        lambda pair: (
            datetime.fromtimestamp(min(pair), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            datetime.fromtimestamp(max(pair), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    )


def calculate_duration_python(start_time: str, end_time: str) -> int:
    """Python で ISO 8601 タイムスタンプから処理時間（秒）を算出する.

    benchmark.sh の処理時間算出ロジックと同等の計算を Python で実装する。
    シェルスクリプトでは以下のように算出している:
        start_epoch=$(date -d "$START_TIME" +%s)
        end_epoch=$(date -d "$END_TIME" +%s)
        duration_seconds=$((end_epoch - start_epoch))

    Args:
        start_time: 開始時刻（ISO 8601 形式、例: "2025-01-15T10:00:00Z"）
        end_time: 終了時刻（ISO 8601 形式、例: "2025-01-15T10:05:30Z"）

    Returns:
        処理時間（秒）。end_time - start_time の差分。
    """
    start_dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    start_epoch = int(calendar.timegm(start_dt.timetuple()))
    end_epoch = int(calendar.timegm(end_dt.timetuple()))
    return end_epoch - start_epoch


class TestProperty3DurationCalculationAccuracy:
    """Property 3: 処理時間算出の正確性.

    任意の 2つの ISO 8601 形式タイムスタンプ（終了時刻 >= 開始時刻）に対して、
    算出される処理時間（秒）は終了時刻と開始時刻の差分に等しいこと。

    **Validates: Requirements 5.6**
    Feature: 04-benchmark-shell-script, Property 3: 処理時間算出の正確性
    """

    @given(data=iso8601_timestamps())
    @settings(max_examples=100)
    def test_duration_equals_epoch_difference(self, data: tuple[str, str]) -> None:
        """任意の有効なタイムスタンプペアで処理時間が差分に等しいこと."""
        start_time, end_time = data

        duration = calculate_duration_python(start_time, end_time)

        # 開始・終了の epoch 秒を直接計算して比較
        start_dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        expected = int((end_dt - start_dt).total_seconds())

        assert duration == expected, (
            f"duration={duration} != expected={expected} "
            f"for start={start_time}, end={end_time}"
        )

    @given(data=iso8601_timestamps())
    @settings(max_examples=100)
    def test_duration_is_non_negative(self, data: tuple[str, str]) -> None:
        """終了時刻 >= 開始時刻 なら処理時間は非負であること."""
        start_time, end_time = data

        duration = calculate_duration_python(start_time, end_time)

        assert duration >= 0, f"duration={duration} is negative for start={start_time}, end={end_time}"

    @given(data=iso8601_timestamps())
    @settings(max_examples=100)
    def test_zero_duration_when_same_timestamps(self, data: tuple[str, str]) -> None:
        """同一タイムスタンプの場合、処理時間は 0 であること."""
        start_time, _ = data

        duration = calculate_duration_python(start_time, start_time)

        assert duration == 0, f"duration={duration} != 0 for identical timestamps {start_time}"


class TestDurationCalcShellIntegration:
    """シェルスクリプトの処理時間算出ロジックと Python 実装の一致を検証する.

    subprocess で bash を呼び出し、シェルの epoch 変換結果と Python の結果を比較する。
    """

    def _shell_duration(self, start_time: str, end_time: str) -> int:
        """bash で処理時間を算出する.

        benchmark.sh と同じロジックを bash で実行し、結果を返す。

        Args:
            start_time: 開始時刻（ISO 8601 形式）
            end_time: 終了時刻（ISO 8601 形式）

        Returns:
            処理時間（秒）
        """
        script = f"""
start_epoch=$(date -d "{start_time}" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "{start_time}" +%s 2>/dev/null || echo "0")
end_epoch=$(date -d "{end_time}" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "{end_time}" +%s 2>/dev/null || echo "0")
echo $((end_epoch - start_epoch))
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(result.stdout.strip())

    def test_shell_matches_python_basic(self) -> None:
        """基本的なタイムスタンプペアでシェルと Python の結果が一致すること."""
        start = "2025-01-15T10:00:00Z"
        end = "2025-01-15T10:05:30Z"

        shell_result = self._shell_duration(start, end)
        python_result = calculate_duration_python(start, end)

        assert shell_result == python_result == 330

    def test_shell_matches_python_large_gap(self) -> None:
        """大きな時間差でもシェルと Python の結果が一致すること."""
        start = "2024-01-01T00:00:00Z"
        end = "2025-01-01T00:00:00Z"

        shell_result = self._shell_duration(start, end)
        python_result = calculate_duration_python(start, end)

        # 2024 年はうるう年: 366 日 = 31622400 秒
        assert shell_result == python_result == 366 * 86400

    def test_shell_matches_python_same_time(self) -> None:
        """同一時刻でシェルと Python の結果が 0 で一致すること."""
        ts = "2025-06-15T12:30:45Z"

        shell_result = self._shell_duration(ts, ts)
        python_result = calculate_duration_python(ts, ts)

        assert shell_result == python_result == 0

    def test_shell_matches_python_one_second(self) -> None:
        """1秒差でシェルと Python の結果が一致すること."""
        start = "2025-03-20T23:59:59Z"
        end = "2025-03-21T00:00:00Z"

        shell_result = self._shell_duration(start, end)
        python_result = calculate_duration_python(start, end)

        assert shell_result == python_result == 1
