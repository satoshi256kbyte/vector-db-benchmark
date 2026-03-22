"""Fargate 概算コスト算出のプロパティベーステスト.

Property 4: Fargate 概算コスト算出の正確性
任意の正の実行時間（秒）に対して、Fargate 概算コストは
(duration_seconds / 3600) * (vcpu * 0.05056 + memory_gb * 0.00553)
に等しいこと（浮動小数点誤差を許容）。

Feature: 04-benchmark-shell-script, Property 4: Fargate 概算コスト算出の正確性
"""

from __future__ import annotations

import subprocess
from decimal import ROUND_DOWN, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

# Fargate 料金定数（ap-northeast-1）
VCPU_RATE = Decimal("0.05056")
MEMORY_RATE = Decimal("0.00553")
VCPU = 2
MEMORY_GB = 4


def calculate_fargate_cost_python(duration_seconds: int) -> Decimal:
    """Python で Fargate 概算コストを算出する（bc の scale 動作を再現）.

    benchmark.sh の calculate_fargate_cost と同等の計算を Python で実装する。
    シェルスクリプトでは bc を使用し、中間計算は scale=6 で算出する:
        hours=$(echo "scale=6; $duration_seconds / 3600" | bc)
        vcpu_cost=$(echo "scale=6; $hours * $vcpu * 0.05056" | bc)
        memory_cost=$(echo "scale=6; $hours * $memory_gb * 0.00553" | bc)
        echo "scale=4; $vcpu_cost + $memory_cost" | bc

    bc の scale は除算・乗算に適用され切り捨て（truncation）で動作する。
    加算では scale は適用されず、オペランドの精度が保持される。
    最終行の scale=4 は除算がないため加算結果に影響しない。

    Args:
        duration_seconds: 実行時間（秒）。正の整数。

    Returns:
        Fargate 概算コスト（USD）。bc の scale=6 中間精度に準拠。
    """
    scale6 = Decimal("0.000001")

    # scale=6 で hours を算出（bc は除算で切り捨て）
    hours = (Decimal(duration_seconds) / Decimal(3600)).quantize(scale6, rounding=ROUND_DOWN)

    # scale=6 で vcpu_cost を算出（bc は乗算でも scale を適用して切り捨て）
    vcpu_cost = (hours * VCPU * VCPU_RATE).quantize(scale6, rounding=ROUND_DOWN)

    # scale=6 で memory_cost を算出
    memory_cost = (hours * MEMORY_GB * MEMORY_RATE).quantize(scale6, rounding=ROUND_DOWN)

    # 最終行の scale=4 は除算がないため加算結果に影響しない
    return vcpu_cost + memory_cost


def calculate_fargate_cost_formula(duration_seconds: int) -> float:
    """数学的な公式でコストを算出する（bc の丸め動作なし）.

    (duration_seconds / 3600) * (vcpu * 0.05056 + memory_gb * 0.00553)

    Args:
        duration_seconds: 実行時間（秒）。正の整数。

    Returns:
        Fargate 概算コスト（USD）。浮動小数点数。
    """
    return (duration_seconds / 3600) * (VCPU * float(VCPU_RATE) + MEMORY_GB * float(MEMORY_RATE))


def normalize_bc_output(bc_output: str) -> Decimal:
    """bc の出力文字列を正規化して Decimal に変換する.

    bc は 1 未満の値で先頭のゼロを省略する（例: ".123" → "0.123"）。

    Args:
        bc_output: bc コマンドの出力文字列。

    Returns:
        正規化された Decimal 値。
    """
    s = bc_output.strip()
    if s.startswith("."):
        s = f"0{s}"
    elif s.startswith("-."):
        s = f"-0{s[1:]}"
    return Decimal(s)


class TestProperty4FargateCostCalculationAccuracy:
    """Property 4: Fargate 概算コスト算出の正確性.

    任意の正の実行時間（秒）に対して、Fargate 概算コストは
    (duration_seconds / 3600) * (vcpu * 0.05056 + memory_gb * 0.00553)
    に等しいこと（浮動小数点誤差を許容）。

    **Validates: Requirements 8.3**
    Feature: 04-benchmark-shell-script, Property 4: Fargate 概算コスト算出の正確性
    """

    @given(duration_seconds=st.integers(min_value=1, max_value=86400 * 7))
    @settings(max_examples=100)
    def test_cost_matches_formula(self, duration_seconds: int) -> None:
        """Python 実装のコストが数学的公式と一致すること（浮動小数点誤差許容）."""
        python_cost = calculate_fargate_cost_python(duration_seconds)
        formula_cost = calculate_fargate_cost_formula(duration_seconds)

        # bc の scale=6 切り捨てによる誤差を許容
        assert abs(float(python_cost) - formula_cost) < 1e-3, (
            f"cost mismatch for duration={duration_seconds}s: "
            f"python={python_cost}, formula={formula_cost:.6f}"
        )

    @given(duration_seconds=st.integers(min_value=1, max_value=86400 * 7))
    @settings(max_examples=100)
    def test_cost_is_non_negative(self, duration_seconds: int) -> None:
        """正の実行時間に対してコストは非負であること."""
        cost = calculate_fargate_cost_python(duration_seconds)

        assert cost >= 0, f"cost={cost} is negative for duration={duration_seconds}s"

    @given(duration_seconds=st.integers(min_value=1, max_value=86400 * 7))
    @settings(max_examples=100)
    def test_cost_increases_with_duration(self, duration_seconds: int) -> None:
        """実行時間が長いほどコストが高い（または同等）であること."""
        cost_base = calculate_fargate_cost_python(duration_seconds)
        cost_longer = calculate_fargate_cost_python(duration_seconds + 3600)

        assert cost_longer >= cost_base, (
            f"cost did not increase: base={cost_base} (duration={duration_seconds}s), "
            f"longer={cost_longer} (duration={duration_seconds + 3600}s)"
        )


class TestFargateCostShellIntegration:
    """シェルスクリプトの Fargate コスト算出ロジックと Python 実装の一致を検証する.

    subprocess で bash + bc を呼び出し、シェルの計算結果と Python の結果を比較する。
    """

    def _shell_fargate_cost(self, duration_seconds: int) -> Decimal:
        """bash + bc で Fargate コストを算出する.

        benchmark.sh の calculate_fargate_cost と同じロジックを bash で実行する。

        Args:
            duration_seconds: 実行時間（秒）

        Returns:
            コスト（Decimal）
        """
        script = f"""
hours=$(echo "scale=6; {duration_seconds} / 3600" | bc)
vcpu_cost=$(echo "scale=6; $hours * 2 * 0.05056" | bc)
memory_cost=$(echo "scale=6; $hours * 4 * 0.00553" | bc)
echo "scale=4; $vcpu_cost + $memory_cost" | bc
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return normalize_bc_output(result.stdout)

    def test_shell_matches_python_one_hour(self) -> None:
        """1時間（3600秒）でシェルと Python の結果が一致すること."""
        duration = 3600

        shell_result = self._shell_fargate_cost(duration)
        python_result = calculate_fargate_cost_python(duration)

        assert shell_result == python_result, (
            f"shell={shell_result}, python={python_result} for duration={duration}s"
        )

    def test_shell_matches_python_short_duration(self) -> None:
        """短時間（60秒）でシェルと Python の結果が一致すること."""
        duration = 60

        shell_result = self._shell_fargate_cost(duration)
        python_result = calculate_fargate_cost_python(duration)

        assert shell_result == python_result, (
            f"shell={shell_result}, python={python_result} for duration={duration}s"
        )

    def test_shell_matches_python_large_duration(self) -> None:
        """長時間（86400秒 = 24時間）でシェルと Python の結果が一致すること."""
        duration = 86400

        shell_result = self._shell_fargate_cost(duration)
        python_result = calculate_fargate_cost_python(duration)

        assert shell_result == python_result, (
            f"shell={shell_result}, python={python_result} for duration={duration}s"
        )

    def test_shell_matches_python_one_second(self) -> None:
        """最小値（1秒）でシェルと Python の結果が一致すること."""
        duration = 1

        shell_result = self._shell_fargate_cost(duration)
        python_result = calculate_fargate_cost_python(duration)

        assert shell_result == python_result, (
            f"shell={shell_result}, python={python_result} for duration={duration}s"
        )

    def test_shell_matches_python_arbitrary_value(self) -> None:
        """任意の値（12345秒）でシェルと Python の結果が一致すること."""
        duration = 12345

        shell_result = self._shell_fargate_cost(duration)
        python_result = calculate_fargate_cost_python(duration)

        assert shell_result == python_result, (
            f"shell={shell_result}, python={python_result} for duration={duration}s"
        )
