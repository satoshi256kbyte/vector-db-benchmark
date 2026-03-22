#!/usr/bin/env bats
# Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
# **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8**

# =============================================================================
# ヘルパー: benchmark.sh からデフォルト値と parse_args 関数のみを安全にロードする
# エントリポイント（parse_args "$@", check_prerequisites, main）は実行しない
# =============================================================================

setup() {
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    BENCHMARK_SCRIPT="$PROJECT_ROOT/scripts/benchmark.sh"

    # benchmark.sh からエントリポイント以前の部分を抽出して eval する
    # - set -euo pipefail を無効化（テスト環境で問題を起こすため）
    # - trap 行を除外
    # - エントリポイントセクション以降を除外
    eval "$(sed -n '1,/^# エントリポイント$/p' "$BENCHMARK_SCRIPT" \
        | sed 's/^set -euo pipefail$//' \
        | grep -v '^trap ' \
        | grep -v '^parse_args "\$@"' \
        | grep -v '^check_prerequisites$' \
        | grep -v '^main$')"
}

# =============================================================================
# テスト: 引数なしの場合、全デフォルト値が正しく設定されること
# =============================================================================

@test "デフォルト値: 引数なしで全デフォルト値が設定される" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args

    [ "$RECORD_COUNT" = "100000" ]
    [ "$AURORA_CLUSTER" = "vdbbench-dev-aurora-pgvector" ]
    [ "$OPENSEARCH_COLLECTION" = "vdbbench-dev-oss-vector" ]
    [ "$S3VECTORS_BUCKET" = "vdbbench-dev-s3vectors-benchmark" ]
    [ "$ECS_CLUSTER" = "vdbbench-dev-ecs-benchmark" ]
    [ "$REGION" = "ap-northeast-1" ]
}

# =============================================================================
# テスト: 個別引数のオーバーライド
# =============================================================================

@test "--record-count で RECORD_COUNT がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --record-count 50000

    [ "$RECORD_COUNT" = "50000" ]
}

@test "--aurora-cluster で AURORA_CLUSTER がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --aurora-cluster my-custom-cluster

    [ "$AURORA_CLUSTER" = "my-custom-cluster" ]
}

@test "--opensearch-collection で OPENSEARCH_COLLECTION がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --opensearch-collection my-collection

    [ "$OPENSEARCH_COLLECTION" = "my-collection" ]
}

@test "--s3vectors-bucket で S3VECTORS_BUCKET がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --s3vectors-bucket my-bucket

    [ "$S3VECTORS_BUCKET" = "my-bucket" ]
}

@test "--ecs-cluster で ECS_CLUSTER がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --ecs-cluster my-ecs-cluster

    [ "$ECS_CLUSTER" = "my-ecs-cluster" ]
}

@test "--region で REGION がオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --region us-west-2

    [ "$REGION" = "us-west-2" ]
}


# =============================================================================
# テスト: 複数引数の組み合わせ
# =============================================================================

@test "複数引数を同時に指定した場合、全て正しくオーバーライドされる" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args \
        --record-count 200000 \
        --aurora-cluster custom-aurora \
        --region eu-west-1

    [ "$RECORD_COUNT" = "200000" ]
    [ "$AURORA_CLUSTER" = "custom-aurora" ]
    [ "$REGION" = "eu-west-1" ]
}

@test "一部の引数のみ指定した場合、未指定の引数はデフォルト値を保持する" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args --record-count 5000 --region us-east-1

    # 指定した引数はオーバーライドされる
    [ "$RECORD_COUNT" = "5000" ]
    [ "$REGION" = "us-east-1" ]

    # 未指定の引数はデフォルト値を保持する
    [ "$AURORA_CLUSTER" = "vdbbench-dev-aurora-pgvector" ]
    [ "$OPENSEARCH_COLLECTION" = "vdbbench-dev-oss-vector" ]
    [ "$S3VECTORS_BUCKET" = "vdbbench-dev-s3vectors-benchmark" ]
    [ "$ECS_CLUSTER" = "vdbbench-dev-ecs-benchmark" ]
}

@test "全引数を同時に指定した場合、全てオーバーライドされデフォルト値は残らない" {
    # Feature: 04-benchmark-shell-script, Property 6: コマンドライン引数パースとデフォルト値
    parse_args \
        --record-count 999 \
        --aurora-cluster a-cluster \
        --opensearch-collection o-collection \
        --s3vectors-bucket s-bucket \
        --ecs-cluster e-cluster \
        --region ap-southeast-1

    [ "$RECORD_COUNT" = "999" ]
    [ "$AURORA_CLUSTER" = "a-cluster" ]
    [ "$OPENSEARCH_COLLECTION" = "o-collection" ]
    [ "$S3VECTORS_BUCKET" = "s-bucket" ]
    [ "$ECS_CLUSTER" = "e-cluster" ]
    [ "$REGION" = "ap-southeast-1" ]
}

# =============================================================================
# テスト: --help オプションの出力確認
# **Validates: Requirements 10.9**
# =============================================================================

@test "--help オプションで Usage 情報が表示され、終了コード 0 で終了する" {
    run bash "$BENCHMARK_SCRIPT" --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"--record-count"* ]]
    [[ "$output" == *"--help"* ]]
}

# =============================================================================
# テスト: 前提条件チェック（aws, psql, jq 不在時のエラー）
# **Validates: Requirements 10.9, 11.5**
# =============================================================================

@test "check_prerequisites: aws 不在時にエラー終了する" {
    run bash -c '
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$BENCHMARK_SCRIPT"'" \
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
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$BENCHMARK_SCRIPT"'" \
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
# テスト: DB 処理順序（Aurora → OpenSearch → S3 Vectors）の検証
# **Validates: Requirements 12.1**
# =============================================================================

@test "main: DB 処理順序が Aurora → OpenSearch → S3 Vectors であること" {
    run bash -c '
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$BENCHMARK_SCRIPT"'" \
            | sed "s/^set -euo pipefail$//" \
            | grep -v "^trap " \
            | grep -v "^parse_args \"\\\$@\"" \
            | grep -v "^check_prerequisites$" \
            | grep -v "^main$")"
        ORDER=""
        run_benchmark_cycle() { ORDER="${ORDER}$1,"; }
        create_result_dir() { RESULT_DIR=$(mktemp -d); BENCHMARK_ID="test"; }
        generate_summary() { :; }
        print_summary() { :; }
        calculate_fargate_cost() { echo "0"; }
        main
        echo "$ORDER"
    '
    [ "$status" -eq 0 ]
    [[ "$output" == *"aurora,opensearch,s3vectors,"* ]]
}

# =============================================================================
# テスト: エラー発生時の次 DB 継続動作の検証
# **Validates: Requirements 11.3**
# =============================================================================

@test "main: 1つの DB でエラーが発生しても次の DB の処理に進むこと" {
    run bash -c '
        eval "$(sed -n "1,/^# エントリポイント$/p" "'"$BENCHMARK_SCRIPT"'" \
            | sed "s/^set -euo pipefail$//" \
            | grep -v "^trap " \
            | grep -v "^parse_args \"\\\$@\"" \
            | grep -v "^check_prerequisites$" \
            | grep -v "^main$")"
        CALL_COUNT=0
        run_benchmark_cycle() { CALL_COUNT=$((CALL_COUNT + 1)); if [[ "$1" == "aurora" ]]; then return 1; fi; }
        create_result_dir() { RESULT_DIR=$(mktemp -d); BENCHMARK_ID="test"; }
        generate_summary() { :; }
        print_summary() { :; }
        calculate_fargate_cost() { echo "0"; }
        main
        echo "CALL_COUNT=$CALL_COUNT"
    '
    [ "$status" -eq 0 ]
    [[ "$output" == *"CALL_COUNT=3"* ]]
}
