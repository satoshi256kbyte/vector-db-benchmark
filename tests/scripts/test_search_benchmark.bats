#!/usr/bin/env bats
# Feature: 07-search-benchmark-script, Property 1: コマンドライン引数パースとデフォルト値
# **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**

# =============================================================================
# ヘルパー: search-benchmark.sh からデフォルト値と parse_args 関数のみを安全にロードする
# =============================================================================

setup() {
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    SEARCH_BENCHMARK_SCRIPT="$PROJECT_ROOT/scripts/search-benchmark.sh"

    # search-benchmark.sh からエントリポイント以前の部分を抽出して eval する
    eval "$(sed -n '1,/^# エントリポイント$/p' "$SEARCH_BENCHMARK_SCRIPT" \
        | sed 's/^set -euo pipefail$//' \
        | grep -v '^trap ' \
        | grep -v '^parse_args "\$@"' \
        | grep -v '^check_prerequisites$' \
        | grep -v '^main$')"
}

# =============================================================================
# テスト: 引数なしの場合、全デフォルト値が正しく設定されること
# Feature: 07-search-benchmark-script, Property 1
# =============================================================================

@test "デフォルト値: 引数なしで全デフォルト値が設定される" {
    parse_args

    [ "$SEARCH_COUNT" = "100" ]
    [ "$TOP_K" = "10" ]
    [ "$RECORD_COUNT" = "100000" ]
    [ "$FUNCTION_NAME" = "vdbbench-dev-lambda-search-test" ]
    [ "$REGION" = "ap-northeast-1" ]
}

# =============================================================================
# テスト: 個別引数のオーバーライド
# Feature: 07-search-benchmark-script, Property 1
# =============================================================================

@test "--search-count で SEARCH_COUNT がオーバーライドされる" {
    parse_args --search-count 50

    [ "$SEARCH_COUNT" = "50" ]
}

@test "-s で SEARCH_COUNT がオーバーライドされる" {
    parse_args -s 200

    [ "$SEARCH_COUNT" = "200" ]
}

@test "--top-k で TOP_K がオーバーライドされる" {
    parse_args --top-k 20

    [ "$TOP_K" = "20" ]
}

@test "-k で TOP_K がオーバーライドされる" {
    parse_args -k 5

    [ "$TOP_K" = "5" ]
}

@test "--record-count で RECORD_COUNT がオーバーライドされる" {
    parse_args --record-count 50000

    [ "$RECORD_COUNT" = "50000" ]
}

@test "-r で RECORD_COUNT がオーバーライドされる" {
    parse_args -r 200000

    [ "$RECORD_COUNT" = "200000" ]
}

@test "--function-name で FUNCTION_NAME がオーバーライドされる" {
    parse_args --function-name my-custom-function

    [ "$FUNCTION_NAME" = "my-custom-function" ]
}

@test "-f で FUNCTION_NAME がオーバーライドされる" {
    parse_args -f another-function

    [ "$FUNCTION_NAME" = "another-function" ]
}

@test "--region で REGION がオーバーライドされる" {
    parse_args --region us-west-2

    [ "$REGION" = "us-west-2" ]
}

# =============================================================================
# テスト: 複数引数の組み合わせ
# Feature: 07-search-benchmark-script, Property 1
# =============================================================================

@test "複数引数を同時に指定した場合、全て正しくオーバーライドされる" {
    parse_args \
        --search-count 500 \
        --top-k 20 \
        --region eu-west-1

    [ "$SEARCH_COUNT" = "500" ]
    [ "$TOP_K" = "20" ]
    [ "$REGION" = "eu-west-1" ]
}

@test "一部の引数のみ指定した場合、未指定の引数はデフォルト値を保持する" {
    parse_args --search-count 50 --region us-east-1

    [ "$SEARCH_COUNT" = "50" ]
    [ "$REGION" = "us-east-1" ]
    [ "$TOP_K" = "10" ]
    [ "$RECORD_COUNT" = "100000" ]
    [ "$FUNCTION_NAME" = "vdbbench-dev-lambda-search-test" ]
}

@test "全引数を同時に指定した場合、全てオーバーライドされデフォルト値は残らない" {
    parse_args \
        --search-count 999 \
        --top-k 50 \
        --record-count 500000 \
        --function-name custom-func \
        --region ap-southeast-1

    [ "$SEARCH_COUNT" = "999" ]
    [ "$TOP_K" = "50" ]
    [ "$RECORD_COUNT" = "500000" ]
    [ "$FUNCTION_NAME" = "custom-func" ]
    [ "$REGION" = "ap-southeast-1" ]
}

@test "短縮オプションと長いオプションを混在させた場合、全て正しくオーバーライドされる" {
    parse_args \
        -s 300 \
        --top-k 15 \
        -r 75000 \
        --function-name mixed-func

    [ "$SEARCH_COUNT" = "300" ]
    [ "$TOP_K" = "15" ]
    [ "$RECORD_COUNT" = "75000" ]
    [ "$FUNCTION_NAME" = "mixed-func" ]
}

# =============================================================================
# テスト: --help オプション
# **Validates: Requirements 4.6**
# =============================================================================

@test "--help オプションで Usage 情報が表示され、終了コード 0 で終了する" {
    run bash "$SEARCH_BENCHMARK_SCRIPT" --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"--search-count"* ]]
    [[ "$output" == *"--top-k"* ]]
    [[ "$output" == *"--record-count"* ]]
    [[ "$output" == *"--function-name"* ]]
    [[ "$output" == *"--region"* ]]
    [[ "$output" == *"--help"* ]]
}

@test "-h オプションで Usage 情報が表示され、終了コード 0 で終了する" {
    run bash "$SEARCH_BENCHMARK_SCRIPT" -h
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
}

# =============================================================================
# テスト: 前提条件チェック
# **Validates: Requirements 5.2, 5.3**
# =============================================================================

@test "check_prerequisites: aws 不在時にエラー終了する" {
    run bash -c '
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$SEARCH_BENCHMARK_SCRIPT"'" \
            | sed "s/^set -euo pipefail$//" \
            | grep -v "^trap " \
            | grep -v "^parse_args \"\\\$@\"" \
            | grep -v "^check_prerequisites$" \
            | grep -v "^main$")"
        command() { if [[ "$2" == "aws" ]]; then return 1; fi; builtin command "$@"; }
        check_prerequisites
    '
    [ "$status" -ne 0 ]
    [[ "$output" == *"aws"* ]]
}

@test "check_prerequisites: jq 不在時にエラー終了する" {
    run bash -c '
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$SEARCH_BENCHMARK_SCRIPT"'" \
            | sed "s/^set -euo pipefail$//" \
            | grep -v "^trap " \
            | grep -v "^parse_args \"\\\$@\"" \
            | grep -v "^check_prerequisites$" \
            | grep -v "^main$")"
        command() { if [[ "$2" == "jq" ]]; then return 1; fi; builtin command "$@"; }
        check_prerequisites
    '
    [ "$status" -ne 0 ]
    [[ "$output" == *"jq"* ]]
}

# =============================================================================
# テスト: コンソールサマリー出力の完全性
# Feature: 07-search-benchmark-script, Property 4
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
# =============================================================================

@test "print_search_summary: 各DBのレイテンシ統計・QPS・成否がコンソールに表示される" {
    # テスト用の一時ディレクトリとサマリー JSON を作成
    RESULT_DIR=$(mktemp -d)

    cat > "${RESULT_DIR}/search-summary.json" <<'SUMMARY_EOF'
{
    "benchmark_id": "20250115-100000",
    "region": "ap-northeast-1",
    "search_params": {"search_count": 100, "top_k": 10, "record_count": 100000},
    "results": {
        "aurora_pgvector": {
            "latency": {"avg_ms": 12.5, "p50_ms": 11.2, "p95_ms": 25.3, "p99_ms": 45.1, "min_ms": 5.1, "max_ms": 52.3},
            "throughput_qps": 80.5,
            "success": true
        },
        "opensearch": {
            "latency": {"avg_ms": 8.3, "p50_ms": 7.1, "p95_ms": 18.5, "p99_ms": 32.0, "min_ms": 3.2, "max_ms": 40.1},
            "throughput_qps": 120.3,
            "success": true
        },
        "s3vectors": {
            "latency": {"avg_ms": 15.7, "p50_ms": 14.3, "p95_ms": 30.2, "p99_ms": 55.8, "min_ms": 6.5, "max_ms": 60.2},
            "throughput_qps": 63.7,
            "success": true
        }
    },
    "comparison": [],
    "total_duration_seconds": 45,
    "completed_at": "2025-01-15T10:01:00Z"
}
SUMMARY_EOF

    run print_search_summary

    [ "$status" -eq 0 ]

    # 各 DB 名が表示されること
    [[ "$output" == *"aurora_pgvector"* ]]
    [[ "$output" == *"opensearch"* ]]
    [[ "$output" == *"s3vectors"* ]]

    # レイテンシ統計値が表示されること
    [[ "$output" == *"12.5"* ]]
    [[ "$output" == *"11.2"* ]]
    [[ "$output" == *"25.3"* ]]
    [[ "$output" == *"45.1"* ]]
    [[ "$output" == *"8.3"* ]]
    [[ "$output" == *"7.1"* ]]
    [[ "$output" == *"18.5"* ]]
    [[ "$output" == *"32"* ]]
    [[ "$output" == *"15.7"* ]]
    [[ "$output" == *"14.3"* ]]
    [[ "$output" == *"30.2"* ]]
    [[ "$output" == *"55.8"* ]]

    # QPS が表示されること
    [[ "$output" == *"80.5"* ]]
    [[ "$output" == *"120.3"* ]]
    [[ "$output" == *"63.7"* ]]

    # 成否マークが表示されること
    [[ "$output" == *"✓"* ]]

    # 結果保存先が表示されること
    [[ "$output" == *"結果保存先"* ]]

    # クリーンアップ
    rm -rf "$RESULT_DIR"
}
