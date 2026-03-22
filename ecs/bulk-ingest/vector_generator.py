"""決定論的ベクトル生成モジュール."""

from __future__ import annotations

import random

VECTOR_DIMENSION = 1536


def generate_vector(seed: int) -> list[float]:
    """決定論的シードから1536次元ベクトルを生成する.

    Args:
        seed: ベクトル生成用のシード値

    Returns:
        1536次元の浮動小数点数ベクトル（各要素は -1.0 以上 1.0 以下）
    """
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(VECTOR_DIMENSION)]


def generate_query_vectors(
    record_count: int,
    search_count: int,
) -> list[list[float]]:
    """投入済みデータからランダムにサンプリングしたクエリベクトルを生成する.

    投入時と同じシードを使用するため、各クエリは必ず実データにヒットする。

    Args:
        record_count: 投入済みレコード数
        search_count: 生成するクエリベクトル数

    Returns:
        クエリベクトルのリスト
    """
    rng = random.Random(42)  # サンプリング用の固定シード
    indices = [rng.randint(0, record_count - 1) for _ in range(search_count)]
    return [generate_vector(i) for i in indices]
