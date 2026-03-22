"""結果 JSON の必須フィールド完全性のプロパティベーステスト.

Property 5: 結果 JSON の必須フィールド完全性
任意のベンチマーク実行結果に対して、個別 DB 結果 JSON は database、record_count、
pre_count、post_count、start_time、end_time、duration_seconds、
throughput_records_per_sec、success の全フィールドを含み、
サマリー JSON は benchmark_id、region、record_count、results（3 DB 分）、
cost_summary の全フィールドを含むこと。

Feature: 04-benchmark-shell-script, Property 5: 結果 JSON の必須フィールド完全性
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# benchmark.sh のパス
BENCHMARK_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "benchmark.sh"

# 有効な DB 名
VALID_DATABASES = ["aurora_pgvector", "opensearch", "s3vectors"]

# 個別 DB 結果 JSON の必須フィールド（Property 5 で定義）
INDIVIDUAL_REQUIRED_FIELDS = {
    "database",
    "record_count",
    "pre_count",
    "post_count",
    "start_time",
    "end_time",
    "duration_seconds",
    "throughput_records_per_sec",
    "success",
}

# サマリー JSON の必須フィールド（Property 5 で定義）
SUMMARY_REQUIRED_FIELDS = {
    "benchmark_id",
    "region",
    "record_count",
    "results",
    "cost_summary",
}

# サマリー results 内の必須キー
SUMMARY_RESULTS_KEYS = {"aurora_pgvector", "opensearch", "s3vectors"}

# サマリー cost_summary 内の必須キー
SUMMARY_COST_SUMMARY_KEYS = {
    "aurora_acu_peak",
    "aurora_acu_cost_usd",
    "opensearch_ocu_peak",
    "opensearch_ocu_cost_usd",
    "s3vectors_cost_usd",
    "fargate_total_seconds",
    "fargate_vcpu",
    "fargate_memory_gb",
    "fargate_estimated_cost_usd",
}


def _build_save_result_json_script(
    result_dir: str,
    database: str,
    record_count: int,
    pre_count: int,
    post_count: int,
    start_time: str,
    end_time: str,
    duration_seconds: int,
    index_drop_success: bool,
    index_create_success: bool,
    ecs_task_arn: str,
    ecs_exit_code: int,
    acu_during: int,
    success: bool,
    error_message: str,
) -> str:
    """save_result_json を呼び出す bash スクリプトを構築する.

    benchmark.sh から save_result_json と log_info 関数を source し、
    RESULT_DIR を設定してから save_result_json を呼び出す。

    Args:
        result_dir: 結果ファイルの出力先ディレクトリ。
        database: DB 識別名。
        record_count: 投入レコード数。
        pre_count: 投入前レコード数。
        post_count: 投入後レコード数。
        start_time: 開始時刻（ISO 8601）。
        end_time: 終了時刻（ISO 8601）。
        duration_seconds: 処理時間（秒）。
        index_drop_success: インデックス削除成功フラグ。
        index_create_success: インデックス作成成功フラグ。
        ecs_task_arn: ECS タスク ARN。
        ecs_exit_code: ECS タスク終了コード。
        acu_during: ACU ピーク値。
        success: 成功フラグ。
        error_message: エラーメッセージ。

    Returns:
        実行可能な bash スクリプト文字列。
    """
    bool_str = lambda b: "true" if b else "false"  # noqa: E731
    return f"""
set -euo pipefail
RESULT_DIR="{result_dir}"
log_info() {{ echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') $*"; }}

{_read_save_result_json_function()}

save_result_json \
    "{database}" \
    {record_count} \
    {pre_count} \
    {post_count} \
    "{start_time}" \
    "{end_time}" \
    {duration_seconds} \
    {bool_str(index_drop_success)} \
    {bool_str(index_create_success)} \
    "{ecs_task_arn}" \
    {ecs_exit_code} \
    {acu_during} \
    {bool_str(success)} \
    "{error_message}"
"""


def _read_save_result_json_function() -> str:
    """benchmark.sh から save_result_json 関数を抽出する.

    Returns:
        save_result_json 関数の bash コード。
    """
    lines: list[str] = []
    in_function = False
    brace_depth = 0

    with open(BENCHMARK_SCRIPT, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("save_result_json()"):
                in_function = True

            if in_function:
                lines.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth == 0 and len(lines) > 1:
                    break

    return "".join(lines)


def _read_generate_summary_function() -> str:
    """benchmark.sh から generate_summary 関数を抽出する.

    Returns:
        generate_summary 関数の bash コード。
    """
    lines: list[str] = []
    in_function = False
    brace_depth = 0

    with open(BENCHMARK_SCRIPT, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("generate_summary()"):
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


# --- Hypothesis ストラテジ ---

iso8601_timestamps = st.from_regex(
    r"20[2-3][0-9]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z",
    fullmatch=True,
)

ecs_task_arns = st.from_regex(
    r"arn:aws:ecs:ap-northeast-1:[0-9]{12}:task/cluster-[a-z]{4}/[a-f0-9]{8}",
    fullmatch=True,
)


class TestProperty5IndividualResultJson:
    """Property 5: 個別 DB 結果 JSON の必須フィールド完全性.

    任意のベンチマーク実行結果に対して、個別 DB 結果 JSON は
    database、record_count、pre_count、post_count、start_time、end_time、
    duration_seconds、throughput_records_per_sec、success の全フィールドを含むこと。

    **Validates: Requirements 9.2**
    Feature: 04-benchmark-shell-script, Property 5: 結果 JSON の必須フィールド完全性
    """

    @given(
        database=st.sampled_from(VALID_DATABASES),
        record_count=st.integers(min_value=1, max_value=1_000_000),
        pre_count=st.integers(min_value=0, max_value=1_000_000),
        post_count=st.integers(min_value=0, max_value=1_000_000),
        start_time=iso8601_timestamps,
        end_time=iso8601_timestamps,
        duration_seconds=st.integers(min_value=1, max_value=86400),
        index_drop_success=st.booleans(),
        index_create_success=st.booleans(),
        ecs_task_arn=ecs_task_arns,
        ecs_exit_code=st.sampled_from([0, 1, 137]),
        acu_during=st.integers(min_value=0, max_value=10),
        success=st.booleans(),
    )
    @settings(max_examples=100, deadline=None)
    def test_individual_result_contains_all_required_fields(
        self,
        database: str,
        record_count: int,
        pre_count: int,
        post_count: int,
        start_time: str,
        end_time: str,
        duration_seconds: int,
        index_drop_success: bool,
        index_create_success: bool,
        ecs_task_arn: str,
        ecs_exit_code: int,
        acu_during: int,
        success: bool,
    ) -> None:
        """任意の入力パラメータで個別 DB 結果 JSON が必須フィールドを全て含むこと."""
        tmp_dir = tempfile.mkdtemp()
        try:
            script = _build_save_result_json_script(
                result_dir=tmp_dir,
                database=database,
                record_count=record_count,
                pre_count=pre_count,
                post_count=post_count,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration_seconds,
                index_drop_success=index_drop_success,
                index_create_success=index_create_success,
                ecs_task_arn=ecs_task_arn,
                ecs_exit_code=ecs_exit_code,
                acu_during=acu_during,
                success=success,
                error_message="",
            )

            result = _run_bash_script(script)
            assert result.returncode == 0, f"bash failed: stderr={result.stderr}"

            # DB 名からファイルプレフィックスを決定
            prefix_map = {"aurora_pgvector": "aurora", "opensearch": "opensearch", "s3vectors": "s3vectors"}
            file_prefix = prefix_map[database]
            json_path = Path(tmp_dir) / f"{file_prefix}-result.json"

            assert json_path.exists(), f"JSON file not found: {json_path}"

            with open(json_path, encoding="utf-8") as f:
                data: dict[str, object] = json.load(f)

            missing = INDIVIDUAL_REQUIRED_FIELDS - set(data.keys())
            assert not missing, f"Missing required fields: {missing} in {sorted(data.keys())}"
        finally:
            # クリーンアップ
            for p in Path(tmp_dir).glob("*"):
                p.unlink()
            os.rmdir(tmp_dir)


class TestProperty5SummaryJson:
    """Property 5: サマリー JSON の必須フィールド完全性.

    任意のベンチマーク実行結果に対して、サマリー JSON は
    benchmark_id、region、record_count、results（3 DB 分）、cost_summary の
    全フィールドを含むこと。

    **Validates: Requirements 9.4**
    Feature: 04-benchmark-shell-script, Property 5: 結果 JSON の必須フィールド完全性
    """

    @given(
        record_count=st.integers(min_value=1, max_value=1_000_000),
        total_duration=st.integers(min_value=1, max_value=86400),
        fargate_total=st.integers(min_value=1, max_value=86400),
        aurora_acu_peak=st.integers(min_value=0, max_value=10),
        opensearch_ocu_peak=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_summary_contains_all_required_fields(
        self,
        record_count: int,
        total_duration: int,
        fargate_total: int,
        aurora_acu_peak: int,
        opensearch_ocu_peak: int,
    ) -> None:
        """任意の入力パラメータでサマリー JSON が必須フィールドを全て含むこと."""
        tmp_dir = tempfile.mkdtemp()
        try:
            benchmark_id = "20250115-100000"
            region = "ap-northeast-1"

            # 各 DB の個別結果 JSON を事前に作成（service_cost_usd を含む）
            for db_name, prefix in [("aurora_pgvector", "aurora"), ("opensearch", "opensearch"), ("s3vectors", "s3vectors")]:
                individual = {
                    "database": db_name,
                    "record_count": record_count,
                    "pre_count": 0,
                    "post_count": record_count,
                    "start_time": "2025-01-15T10:00:00Z",
                    "end_time": "2025-01-15T10:05:00Z",
                    "duration_seconds": 300,
                    "throughput_records_per_sec": round(record_count / 300, 2),
                    "index_drop_success": True,
                    "index_create_success": True,
                    "ecs_task_arn": "arn:aws:ecs:ap-northeast-1:123456789012:task/cluster/abc123",
                    "ecs_exit_code": 0,
                    "acu_during": 8,
                    "opensearch_ocu_peak": 0,
                    "index_create_duration_seconds": 0,
                    "service_cost_usd": 0.5,
                    "success": True,
                    "error_message": None,
                }
                with open(Path(tmp_dir) / f"{prefix}-result.json", "w", encoding="utf-8") as f:
                    json.dump(individual, f)

            # Fargate コスト概算（簡易計算）
            fargate_cost = round((fargate_total / 3600) * (2 * 0.05056 + 4 * 0.00553), 4)

            generate_summary_func = _read_generate_summary_function()

            # generate_summary は 8 引数: total_duration, fargate_total, fargate_cost,
            # aurora_acu_peak, opensearch_ocu_peak, aurora_service_cost, opensearch_service_cost, s3vectors_service_cost
            script = f"""
set -euo pipefail
RESULT_DIR="{tmp_dir}"
BENCHMARK_ID="{benchmark_id}"
REGION="{region}"
RECORD_COUNT={record_count}
log_info() {{ echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') $*"; }}

{generate_summary_func}

generate_summary {total_duration} {fargate_total} {fargate_cost} {aurora_acu_peak} {opensearch_ocu_peak} 0.5 0.5 0.5
"""

            result = _run_bash_script(script)
            assert result.returncode == 0, f"bash failed: stderr={result.stderr}"

            json_path = Path(tmp_dir) / "summary.json"
            assert json_path.exists(), f"Summary JSON not found: {json_path}"

            with open(json_path, encoding="utf-8") as f:
                data: dict[str, object] = json.load(f)

            # トップレベル必須フィールド
            missing_top = SUMMARY_REQUIRED_FIELDS - set(data.keys())
            assert not missing_top, f"Missing top-level fields: {missing_top}"

            # results 内の 3 DB キー
            results = data["results"]
            assert isinstance(results, dict), f"results is not a dict: {type(results)}"
            missing_dbs = SUMMARY_RESULTS_KEYS - set(results.keys())
            assert not missing_dbs, f"Missing DB keys in results: {missing_dbs}"

            # cost_summary 内の必須キー
            cost_summary = data["cost_summary"]
            assert isinstance(cost_summary, dict), f"cost_summary is not a dict: {type(cost_summary)}"
            missing_cost = SUMMARY_COST_SUMMARY_KEYS - set(cost_summary.keys())
            assert not missing_cost, f"Missing cost_summary fields: {missing_cost}"
        finally:
            # クリーンアップ
            for p in Path(tmp_dir).glob("*"):
                p.unlink()
            os.rmdir(tmp_dir)
