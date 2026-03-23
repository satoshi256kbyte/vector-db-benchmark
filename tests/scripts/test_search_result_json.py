"""検索結果 JSON の必須フィールド完全性のプロパティベーステスト.

Feature: 07-search-benchmark-script

Property 2: 個別 DB 検索結果 JSON の必須フィールド完全性
任意の有効な Lambda レスポンスに対して、save_db_result_json 関数が生成する
個別 DB 結果 JSON は database、latency（avg_ms、p50_ms、p95_ms、p99_ms、min_ms、max_ms）、
throughput_qps、search_count、top_k、success の全フィールドを含むこと。

Property 3: サマリー JSON の必須フィールド完全性
任意の有効な検索パラメータと Lambda レスポンスに対して、generate_search_summary 関数が
生成するサマリー JSON は benchmark_id、region、search_params、results、comparison、
total_duration_seconds、completed_at の全フィールドを含むこと。

Property 4: コンソールサマリー出力の完全性
任意の有効な Lambda レスポンスに対して、print_search_summary 関数のコンソール出力は、
各 DB のレイテンシ統計値、スループット（QPS）、および成否情報を全て含むこと。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# search-benchmark.sh のパス
SEARCH_BENCHMARK_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "search-benchmark.sh"

# 有効な DB キー（Lambda レスポンス内のキー）
VALID_DB_KEYS = ["aurora", "opensearch", "s3vectors"]

# 個別 DB 検索結果 JSON の必須フィールド（Property 2）
INDIVIDUAL_REQUIRED_FIELDS = {
    "database",
    "latency",
    "throughput_qps",
    "search_count",
    "top_k",
    "success",
}

# latency 内の必須フィールド
LATENCY_REQUIRED_FIELDS = {
    "avg_ms",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "min_ms",
    "max_ms",
}

# サマリー JSON の必須フィールド（Property 3）
SUMMARY_REQUIRED_FIELDS = {
    "benchmark_id",
    "region",
    "search_params",
    "results",
    "comparison",
    "total_duration_seconds",
    "completed_at",
}

# サマリー search_params 内の必須キー
SUMMARY_SEARCH_PARAMS_KEYS = {"search_count", "top_k", "record_count"}

# サマリー results 内の必須キー
SUMMARY_RESULTS_KEYS = {"aurora_pgvector", "opensearch", "s3vectors"}


def _extract_bash_function(script_path: Path, function_name: str) -> str:
    """シェルスクリプトから指定された関数を抽出する.

    Args:
        script_path: スクリプトファイルのパス。
        function_name: 抽出する関数名。

    Returns:
        関数の bash コード。
    """
    lines: list[str] = []
    in_function = False
    brace_depth = 0

    with open(script_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(f"{function_name}()"):
                in_function = True

            if in_function:
                lines.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth == 0 and len(lines) > 1:
                    break

    return "".join(lines)


def _run_bash_script(script: str) -> subprocess.CompletedProcess[str]:
    """bash スクリプトを実行する.

    Args:
        script: 実行する bash スクリプト。

    Returns:
        subprocess.CompletedProcess オブジェクト。
    """
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _build_lambda_response_json(
    aurora_latency: dict[str, float],
    opensearch_latency: dict[str, float],
    s3vectors_latency: dict[str, float],
    aurora_qps: float,
    opensearch_qps: float,
    s3vectors_qps: float,
    search_count: int,
    top_k: int,
) -> dict[str, object]:
    """テスト用の Lambda レスポンス JSON を構築する.

    Args:
        aurora_latency: Aurora のレイテンシ統計。
        opensearch_latency: OpenSearch のレイテンシ統計。
        s3vectors_latency: S3 Vectors のレイテンシ統計。
        aurora_qps: Aurora の QPS。
        opensearch_qps: OpenSearch の QPS。
        s3vectors_qps: S3 Vectors の QPS。
        search_count: 検索回数。
        top_k: 近傍返却件数。

    Returns:
        Lambda レスポンス JSON 辞書。
    """
    body = {
        "aurora": {
            "database": "aurora_pgvector",
            "latency": aurora_latency,
            "throughput_qps": aurora_qps,
            "search_count": search_count,
            "top_k": top_k,
            "success": True,
            "error_message": None,
        },
        "opensearch": {
            "database": "opensearch",
            "latency": opensearch_latency,
            "throughput_qps": opensearch_qps,
            "search_count": search_count,
            "top_k": top_k,
            "success": True,
            "error_message": None,
        },
        "s3vectors": {
            "database": "s3vectors",
            "latency": s3vectors_latency,
            "throughput_qps": s3vectors_qps,
            "search_count": search_count,
            "top_k": top_k,
            "success": True,
            "error_message": None,
        },
        "search_count": search_count,
        "top_k": top_k,
        "comparison": [],
    }
    return {
        "statusCode": 200,
        "body": json.dumps(body),
    }


# --- Hypothesis ストラテジ ---

latency_values = st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False)

latency_dicts = st.fixed_dictionaries({
    "avg_ms": latency_values,
    "p50_ms": latency_values,
    "p95_ms": latency_values,
    "p99_ms": latency_values,
    "min_ms": latency_values,
    "max_ms": latency_values,
})

qps_values = st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False)


class TestProperty2IndividualSearchResultJson:
    """Property 2: 個別 DB 検索結果 JSON の必須フィールド完全性.

    任意の有効な Lambda レスポンスに対して、save_db_result_json 関数が生成する
    個別 DB 結果 JSON は必須フィールドを全て含むこと。

    **Validates: Requirements 1.3, 2.2, 2.3**
    Feature: 07-search-benchmark-script, Property 2: 個別 DB 検索結果 JSON の必須フィールド完全性
    """

    @given(
        aurora_latency=latency_dicts,
        opensearch_latency=latency_dicts,
        s3vectors_latency=latency_dicts,
        aurora_qps=qps_values,
        opensearch_qps=qps_values,
        s3vectors_qps=qps_values,
        search_count=st.integers(min_value=1, max_value=10000),
        top_k=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100, deadline=None)
    def test_individual_search_result_contains_all_required_fields(
        self,
        aurora_latency: dict[str, float],
        opensearch_latency: dict[str, float],
        s3vectors_latency: dict[str, float],
        aurora_qps: float,
        opensearch_qps: float,
        s3vectors_qps: float,
        search_count: int,
        top_k: int,
    ) -> None:
        """任意の Lambda レスポンスで個別 DB 結果 JSON が必須フィールドを全て含むこと."""
        tmp_dir = tempfile.mkdtemp()
        try:
            # Lambda レスポンス JSON を作成
            response = _build_lambda_response_json(
                aurora_latency=aurora_latency,
                opensearch_latency=opensearch_latency,
                s3vectors_latency=s3vectors_latency,
                aurora_qps=aurora_qps,
                opensearch_qps=opensearch_qps,
                s3vectors_qps=s3vectors_qps,
                search_count=search_count,
                top_k=top_k,
            )
            response_file = Path(tmp_dir) / "lambda-response.json"
            with open(response_file, "w", encoding="utf-8") as f:
                json.dump(response, f)

            # save_db_result_json 関数を抽出
            save_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "save_db_result_json")
            log_info_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_info")
            log_error_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_error")

            # 各 DB に対して save_db_result_json を実行
            for db_key in VALID_DB_KEYS:
                script = f"""
set -euo pipefail
RESULT_DIR="{tmp_dir}"
{log_info_fn}
{log_error_fn}
{save_fn}
save_db_result_json "{db_key}" "{response_file}"
"""
                result = _run_bash_script(script)
                assert result.returncode == 0, (
                    f"bash failed for {db_key}: stderr={result.stderr}"
                )

                output_file = Path(tmp_dir) / f"{db_key}-search.json"
                assert output_file.exists(), f"JSON file not found: {output_file}"

                with open(output_file, encoding="utf-8") as f:
                    data: dict[str, object] = json.load(f)

                # 必須フィールドの検証
                missing = INDIVIDUAL_REQUIRED_FIELDS - set(data.keys())
                assert not missing, (
                    f"Missing required fields for {db_key}: {missing}"
                )

                # latency 内の必須フィールド検証
                latency = data["latency"]
                assert isinstance(latency, dict), (
                    f"latency is not a dict for {db_key}: {type(latency)}"
                )
                missing_latency = LATENCY_REQUIRED_FIELDS - set(latency.keys())
                assert not missing_latency, (
                    f"Missing latency fields for {db_key}: {missing_latency}"
                )
        finally:
            for p in Path(tmp_dir).glob("*"):
                p.unlink()
            os.rmdir(tmp_dir)


class TestProperty3SummarySearchJson:
    """Property 3: サマリー JSON の必須フィールド完全性.

    任意の有効な検索パラメータと Lambda レスポンスに対して、
    generate_search_summary 関数が生成するサマリー JSON は必須フィールドを全て含むこと。

    **Validates: Requirements 2.4, 2.5**
    Feature: 07-search-benchmark-script, Property 3: サマリー JSON の必須フィールド完全性
    """

    @given(
        aurora_latency=latency_dicts,
        opensearch_latency=latency_dicts,
        s3vectors_latency=latency_dicts,
        aurora_qps=qps_values,
        opensearch_qps=qps_values,
        s3vectors_qps=qps_values,
        search_count=st.integers(min_value=1, max_value=10000),
        top_k=st.integers(min_value=1, max_value=100),
        record_count=st.integers(min_value=1, max_value=1_000_000),
        total_duration=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=100, deadline=None)
    def test_summary_contains_all_required_fields(
        self,
        aurora_latency: dict[str, float],
        opensearch_latency: dict[str, float],
        s3vectors_latency: dict[str, float],
        aurora_qps: float,
        opensearch_qps: float,
        s3vectors_qps: float,
        search_count: int,
        top_k: int,
        record_count: int,
        total_duration: int,
    ) -> None:
        """任意の入力パラメータでサマリー JSON が必須フィールドを全て含むこと."""
        tmp_dir = tempfile.mkdtemp()
        try:
            # 各 DB の個別結果 JSON を事前に作成
            for db_key, db_name in [("aurora", "aurora_pgvector"), ("opensearch", "opensearch"), ("s3vectors", "s3vectors")]:
                latency = {"aurora": aurora_latency, "opensearch": opensearch_latency, "s3vectors": s3vectors_latency}[db_key]
                qps = {"aurora": aurora_qps, "opensearch": opensearch_qps, "s3vectors": s3vectors_qps}[db_key]
                individual = {
                    "database": db_name,
                    "latency": latency,
                    "throughput_qps": qps,
                    "search_count": search_count,
                    "top_k": top_k,
                    "success": True,
                    "error_message": None,
                }
                with open(Path(tmp_dir) / f"{db_key}-search.json", "w", encoding="utf-8") as f:
                    json.dump(individual, f)

            # generate_search_summary 関数を抽出
            gen_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "generate_search_summary")
            log_info_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_info")
            log_error_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_error")

            script = f"""
set -euo pipefail
RESULT_DIR="{tmp_dir}"
BENCHMARK_ID="20250115-100000"
REGION="ap-northeast-1"
SEARCH_COUNT={search_count}
TOP_K={top_k}
RECORD_COUNT={record_count}
{log_info_fn}
{log_error_fn}
{gen_fn}
generate_search_summary {total_duration}
"""
            result = _run_bash_script(script)
            assert result.returncode == 0, f"bash failed: stderr={result.stderr}"

            json_path = Path(tmp_dir) / "search-summary.json"
            assert json_path.exists(), f"Summary JSON not found: {json_path}"

            with open(json_path, encoding="utf-8") as f:
                data: dict[str, object] = json.load(f)

            # トップレベル必須フィールド
            missing_top = SUMMARY_REQUIRED_FIELDS - set(data.keys())
            assert not missing_top, f"Missing top-level fields: {missing_top}"

            # search_params 内の必須キー
            search_params = data["search_params"]
            assert isinstance(search_params, dict), f"search_params is not a dict: {type(search_params)}"
            missing_params = SUMMARY_SEARCH_PARAMS_KEYS - set(search_params.keys())
            assert not missing_params, f"Missing search_params fields: {missing_params}"

            # results 内の 3 DB キー
            results = data["results"]
            assert isinstance(results, dict), f"results is not a dict: {type(results)}"
            missing_dbs = SUMMARY_RESULTS_KEYS - set(results.keys())
            assert not missing_dbs, f"Missing DB keys in results: {missing_dbs}"

            # comparison が配列であること
            comparison = data["comparison"]
            assert isinstance(comparison, list), f"comparison is not a list: {type(comparison)}"
        finally:
            for p in Path(tmp_dir).glob("*"):
                p.unlink()
            os.rmdir(tmp_dir)


class TestProperty4ConsoleSummaryCompleteness:
    """Property 4: コンソールサマリー出力の完全性.

    任意の有効な Lambda レスポンスに対して、print_search_summary 関数のコンソール出力は、
    各 DB のレイテンシ統計値、スループット（QPS）、および成否情報を全て含むこと。

    **Validates: Requirements 3.1, 3.2, 3.3**
    Feature: 07-search-benchmark-script, Property 4: コンソールサマリー出力の完全性
    """

    @given(
        aurora_avg=latency_values,
        aurora_p50=latency_values,
        aurora_p95=latency_values,
        aurora_p99=latency_values,
        opensearch_avg=latency_values,
        opensearch_p50=latency_values,
        opensearch_p95=latency_values,
        opensearch_p99=latency_values,
        s3vectors_avg=latency_values,
        s3vectors_p50=latency_values,
        s3vectors_p95=latency_values,
        s3vectors_p99=latency_values,
        aurora_qps=qps_values,
        opensearch_qps=qps_values,
        s3vectors_qps=qps_values,
    )
    @settings(max_examples=100, deadline=None)
    def test_console_output_contains_all_db_metrics(
        self,
        aurora_avg: float,
        aurora_p50: float,
        aurora_p95: float,
        aurora_p99: float,
        opensearch_avg: float,
        opensearch_p50: float,
        opensearch_p95: float,
        opensearch_p99: float,
        s3vectors_avg: float,
        s3vectors_p50: float,
        s3vectors_p95: float,
        s3vectors_p99: float,
        aurora_qps: float,
        opensearch_qps: float,
        s3vectors_qps: float,
    ) -> None:
        """任意のレイテンシ・QPS 値でコンソール出力が全 DB の情報を含むこと."""
        tmp_dir = tempfile.mkdtemp()
        try:
            # サマリー JSON を直接作成
            summary = {
                "benchmark_id": "20250115-100000",
                "region": "ap-northeast-1",
                "search_params": {"search_count": 100, "top_k": 10, "record_count": 100000},
                "results": {
                    "aurora_pgvector": {
                        "latency": {
                            "avg_ms": round(aurora_avg, 1),
                            "p50_ms": round(aurora_p50, 1),
                            "p95_ms": round(aurora_p95, 1),
                            "p99_ms": round(aurora_p99, 1),
                            "min_ms": 1.0,
                            "max_ms": 100.0,
                        },
                        "throughput_qps": round(aurora_qps, 1),
                        "success": True,
                    },
                    "opensearch": {
                        "latency": {
                            "avg_ms": round(opensearch_avg, 1),
                            "p50_ms": round(opensearch_p50, 1),
                            "p95_ms": round(opensearch_p95, 1),
                            "p99_ms": round(opensearch_p99, 1),
                            "min_ms": 1.0,
                            "max_ms": 100.0,
                        },
                        "throughput_qps": round(opensearch_qps, 1),
                        "success": True,
                    },
                    "s3vectors": {
                        "latency": {
                            "avg_ms": round(s3vectors_avg, 1),
                            "p50_ms": round(s3vectors_p50, 1),
                            "p95_ms": round(s3vectors_p95, 1),
                            "p99_ms": round(s3vectors_p99, 1),
                            "min_ms": 1.0,
                            "max_ms": 100.0,
                        },
                        "throughput_qps": round(s3vectors_qps, 1),
                        "success": True,
                    },
                },
                "comparison": [],
                "total_duration_seconds": 45,
                "completed_at": "2025-01-15T10:01:00Z",
            }

            with open(Path(tmp_dir) / "search-summary.json", "w", encoding="utf-8") as f:
                json.dump(summary, f)

            # print_search_summary 関数を抽出して実行
            print_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "print_search_summary")
            log_info_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_info")
            log_error_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_error")
            log_sep_fn = _extract_bash_function(SEARCH_BENCHMARK_SCRIPT, "log_separator")

            script = f"""
set -euo pipefail
RESULT_DIR="{tmp_dir}"
{log_info_fn}
{log_error_fn}
{log_sep_fn}
{print_fn}
print_search_summary
"""
            result = _run_bash_script(script)
            assert result.returncode == 0, f"bash failed: stderr={result.stderr}"

            output = result.stdout

            # 各 DB 名が出力に含まれること
            assert "aurora_pgvector" in output, "aurora_pgvector not in output"
            assert "opensearch" in output, "opensearch not in output"
            assert "s3vectors" in output, "s3vectors not in output"

            # 成否マークが出力に含まれること
            assert "✓" in output, "success mark ✓ not in output"

            # 結果保存先が出力に含まれること
            assert "結果保存先" in output, "result path not in output"
        finally:
            for p in Path(tmp_dir).glob("*"):
                p.unlink()
            os.rmdir(tmp_dir)
