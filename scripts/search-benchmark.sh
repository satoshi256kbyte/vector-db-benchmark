#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 検索ベンチマークシェルスクリプト
# 検索テスト Lambda を invoke し、3つのベクトルDB（Aurora pgvector,
# OpenSearch Serverless, S3 Vectors）に対する検索ベンチマーク結果を取得・保存・表示する
# =============================================================================

# =============================================================================
# デフォルト値
# =============================================================================
SEARCH_COUNT=100
TOP_K=10
RECORD_COUNT=100000
FUNCTION_NAME="vdbbench-dev-lambda-search-test"
REGION="ap-northeast-1"

# =============================================================================
# プレースホルダー変数
# =============================================================================
RESULT_DIR=""
BENCHMARK_ID=""

# =============================================================================
# ログユーティリティ
# =============================================================================
log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_separator() {
    echo "========================================"
}

# =============================================================================
# ヘルプ表示
# =============================================================================
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

検索テスト Lambda を invoke し、3つのベクトルDB に対する検索ベンチマークを実行する。

Options:
  -s, --search-count N     検索回数 (デフォルト: 100)
  -k, --top-k N            近傍返却件数 (デフォルト: 10)
  -r, --record-count N     投入済みレコード数 (デフォルト: 100000)
  -f, --function-name NAME Lambda 関数名 (デフォルト: vdbbench-dev-lambda-search-test)
      --region REGION      AWS リージョン (デフォルト: ap-northeast-1)
  -h, --help               ヘルプ表示
EOF
}

# =============================================================================
# 引数パース
# =============================================================================
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -s|--search-count)
                SEARCH_COUNT="$2"
                shift 2
                ;;
            -k|--top-k)
                TOP_K="$2"
                shift 2
                ;;
            -r|--record-count)
                RECORD_COUNT="$2"
                shift 2
                ;;
            -f|--function-name)
                FUNCTION_NAME="$2"
                shift 2
                ;;
            --region)
                REGION="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "不明な引数: $1"
                usage
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# 前提条件チェック
# =============================================================================
check_prerequisites() {
    log_info "前提条件を確認中..."

    # aws CLI の存在確認
    if ! command -v aws &>/dev/null; then
        log_error "aws CLI がインストールされていません"
        exit 1
    fi

    # jq の存在確認
    if ! command -v jq &>/dev/null; then
        log_error "jq がインストールされていません"
        exit 1
    fi

    # AWS 認証情報の確認
    if ! aws sts get-caller-identity --region "$REGION" &>/dev/null; then
        log_error "AWS 認証情報が無効です。aws configure または SSO ログインを確認してください"
        exit 1
    fi

    # Lambda 関数の存在確認
    if ! aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
        log_error "Lambda 関数が見つかりません: ${FUNCTION_NAME}"
        exit 1
    fi

    log_info "前提条件チェック完了"
}

# =============================================================================
# クリーンアップ処理
# =============================================================================
cleanup() {
    # 一時ファイルがあれば削除
    if [[ -n "${RESULT_DIR:-}" && -f "${RESULT_DIR}/lambda-response-raw.json" ]]; then
        rm -f "${RESULT_DIR}/lambda-response-raw.json"
    fi
}

trap cleanup EXIT

# =============================================================================
# 結果ディレクトリ作成
# =============================================================================
create_result_dir() {
    BENCHMARK_ID=$(date -u +"%Y%m%d-%H%M%S")
    RESULT_DIR="results/${BENCHMARK_ID}"

    mkdir -p "$RESULT_DIR"
    log_info "結果ディレクトリを作成しました: ${RESULT_DIR}"
}

# =============================================================================
# Lambda invoke
# =============================================================================
invoke_search_lambda() {
    log_info "検索テスト Lambda を invoke 中..."
    log_info "検索パラメータ: search_count=${SEARCH_COUNT}, top_k=${TOP_K}, record_count=${RECORD_COUNT}"
    log_info "Lambda 関数: ${FUNCTION_NAME} (${REGION})"

    local payload
    payload=$(jq -n \
        --argjson search_count "$SEARCH_COUNT" \
        --argjson top_k "$TOP_K" \
        --argjson record_count "$RECORD_COUNT" \
        '{search_count: $search_count, top_k: $top_k, record_count: $record_count}')

    local response_file="${RESULT_DIR}/lambda-response.json"
    local invoke_output

    # Lambda invoke 実行
    invoke_output=$(aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload "$payload" \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        "$response_file" 2>&1) || {
        log_error "Lambda invoke に失敗しました"
        log_error "$invoke_output"
        exit 1
    }

    # FunctionError チェック
    local function_error
    function_error=$(echo "$invoke_output" | jq -r '.FunctionError // empty' 2>/dev/null || echo "")
    if [[ -n "$function_error" ]]; then
        log_error "Lambda 実行エラー: FunctionError=${function_error}"
        log_error "レスポンス: $(cat "$response_file")"
        exit 1
    fi

    # statusCode チェック（レスポンス JSON 内）
    local status_code
    status_code=$(jq -r '.statusCode // empty' "$response_file" 2>/dev/null || echo "")
    if [[ -n "$status_code" && "$status_code" != "200" ]]; then
        log_error "Lambda レスポンスエラー: statusCode=${status_code}"
        log_error "レスポンス: $(cat "$response_file")"
        exit 1
    fi

    log_info "Lambda invoke が完了しました"
}

# =============================================================================
# 個別 DB 検索結果 JSON 保存
# =============================================================================

# Lambda レスポンスから個別 DB の検索結果を抽出して JSON ファイルに保存する
# 引数:
#   $1 - db_key: Lambda レスポンス内のキー（aurora, opensearch, s3vectors）
#   $2 - response_file: Lambda レスポンス JSON ファイルパス
save_db_result_json() {
    local db_key="$1"
    local response_file="$2"

    # body が文字列の場合はパースし、オブジェクトの場合はそのまま使用
    local body_json
    body_json=$(jq -r 'if .body | type == "string" then .body | fromjson else .body // . end' "$response_file")

    local db_result
    db_result=$(echo "$body_json" | jq --arg key "$db_key" '.[$key]')

    if [[ "$db_result" == "null" || -z "$db_result" ]]; then
        log_error "${db_key} の検索結果が見つかりません"
        return 1
    fi

    # ファイル名を決定
    local output_file="${RESULT_DIR}/${db_key}-search.json"

    echo "$db_result" | jq '.' > "$output_file"
    log_info "検索結果を保存しました: ${output_file}"
}

# =============================================================================
# サマリー JSON 生成
# =============================================================================

# 全 DB の結果を統合したサマリー JSON を生成する
# 引数:
#   $1 - total_duration_seconds: 全体の処理時間（秒）
generate_search_summary() {
    local total_duration_seconds="$1"

    local completed_at
    completed_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local output_file="${RESULT_DIR}/search-summary.json"

    # 各 DB の結果を読み込み
    local aurora_result="{}"
    local opensearch_result="{}"
    local s3vectors_result="{}"

    if [[ -f "${RESULT_DIR}/aurora-search.json" ]]; then
        aurora_result=$(jq '{
            latency: .latency,
            throughput_qps: .throughput_qps,
            success: .success
        }' "${RESULT_DIR}/aurora-search.json")
    fi

    if [[ -f "${RESULT_DIR}/opensearch-search.json" ]]; then
        opensearch_result=$(jq '{
            latency: .latency,
            throughput_qps: .throughput_qps,
            success: .success
        }' "${RESULT_DIR}/opensearch-search.json")
    fi

    if [[ -f "${RESULT_DIR}/s3vectors-search.json" ]]; then
        s3vectors_result=$(jq '{
            latency: .latency,
            throughput_qps: .throughput_qps,
            success: .success
        }' "${RESULT_DIR}/s3vectors-search.json")
    fi

    # comparison 配列を構築
    local comparison="[]"
    if [[ -f "${RESULT_DIR}/aurora-search.json" && -f "${RESULT_DIR}/opensearch-search.json" && -f "${RESULT_DIR}/s3vectors-search.json" ]]; then
        comparison=$(jq -n \
            --slurpfile aurora "${RESULT_DIR}/aurora-search.json" \
            --slurpfile opensearch "${RESULT_DIR}/opensearch-search.json" \
            --slurpfile s3vectors "${RESULT_DIR}/s3vectors-search.json" \
            '[
                {metric: "avg_ms", aurora_pgvector: $aurora[0].latency.avg_ms, opensearch: $opensearch[0].latency.avg_ms, s3vectors: $s3vectors[0].latency.avg_ms},
                {metric: "p50_ms", aurora_pgvector: $aurora[0].latency.p50_ms, opensearch: $opensearch[0].latency.p50_ms, s3vectors: $s3vectors[0].latency.p50_ms},
                {metric: "p95_ms", aurora_pgvector: $aurora[0].latency.p95_ms, opensearch: $opensearch[0].latency.p95_ms, s3vectors: $s3vectors[0].latency.p95_ms},
                {metric: "p99_ms", aurora_pgvector: $aurora[0].latency.p99_ms, opensearch: $opensearch[0].latency.p99_ms, s3vectors: $s3vectors[0].latency.p99_ms},
                {metric: "min_ms", aurora_pgvector: $aurora[0].latency.min_ms, opensearch: $opensearch[0].latency.min_ms, s3vectors: $s3vectors[0].latency.min_ms},
                {metric: "max_ms", aurora_pgvector: $aurora[0].latency.max_ms, opensearch: $opensearch[0].latency.max_ms, s3vectors: $s3vectors[0].latency.max_ms},
                {metric: "throughput_qps", aurora_pgvector: $aurora[0].throughput_qps, opensearch: $opensearch[0].throughput_qps, s3vectors: $s3vectors[0].throughput_qps}
            ]')
    fi

    # サマリー JSON を生成
    jq -n \
        --arg benchmark_id "$BENCHMARK_ID" \
        --arg region "$REGION" \
        --argjson search_count "$SEARCH_COUNT" \
        --argjson top_k "$TOP_K" \
        --argjson record_count "$RECORD_COUNT" \
        --argjson aurora_result "$aurora_result" \
        --argjson opensearch_result "$opensearch_result" \
        --argjson s3vectors_result "$s3vectors_result" \
        --argjson comparison "$comparison" \
        --argjson total_duration_seconds "$total_duration_seconds" \
        --arg completed_at "$completed_at" \
        '{
            benchmark_id: $benchmark_id,
            region: $region,
            search_params: {
                search_count: $search_count,
                top_k: $top_k,
                record_count: $record_count
            },
            results: {
                aurora_pgvector: $aurora_result,
                opensearch: $opensearch_result,
                s3vectors: $s3vectors_result
            },
            comparison: $comparison,
            total_duration_seconds: $total_duration_seconds,
            completed_at: $completed_at
        }' > "$output_file"

    log_info "サマリー JSON を保存しました: ${output_file}"
}

# =============================================================================
# コンソールサマリー表示
# =============================================================================
print_search_summary() {
    local summary_file="${RESULT_DIR}/search-summary.json"

    if [[ ! -f "$summary_file" ]]; then
        log_error "サマリーファイルが見つかりません: ${summary_file}"
        return 1
    fi

    log_separator
    echo ""
    echo "  検索ベンチマーク結果サマリー"
    echo ""
    log_separator

    local search_count top_k record_count
    search_count=$(jq -r '.search_params.search_count' "$summary_file")
    top_k=$(jq -r '.search_params.top_k' "$summary_file")
    record_count=$(jq -r '.search_params.record_count' "$summary_file")
    echo "  検索パラメータ: search_count=${search_count}, top_k=${top_k}, record_count=${record_count}"
    echo ""

    # ヘッダー
    printf "  %-20s | %7s | %7s | %7s | %7s | %8s | %s\n" \
        "DB" "avg_ms" "p50_ms" "p95_ms" "p99_ms" "QPS" "成否"
    printf "  --------------------|---------|---------|---------|---------|----------|------\n"

    # 各 DB の結果を表示
    local dbs=("aurora_pgvector" "opensearch" "s3vectors")
    for db in "${dbs[@]}"; do
        local avg_ms p50_ms p95_ms p99_ms qps success success_mark
        avg_ms=$(jq -r ".results.${db}.latency.avg_ms // \"N/A\"" "$summary_file")
        p50_ms=$(jq -r ".results.${db}.latency.p50_ms // \"N/A\"" "$summary_file")
        p95_ms=$(jq -r ".results.${db}.latency.p95_ms // \"N/A\"" "$summary_file")
        p99_ms=$(jq -r ".results.${db}.latency.p99_ms // \"N/A\"" "$summary_file")
        qps=$(jq -r ".results.${db}.throughput_qps // \"N/A\"" "$summary_file")
        success=$(jq -r ".results.${db}.success // \"N/A\"" "$summary_file")

        if [[ "$success" == "true" ]]; then
            success_mark="✓"
        elif [[ "$success" == "false" ]]; then
            success_mark="✗"
        else
            success_mark="N/A"
        fi

        printf "  %-20s | %7s | %7s | %7s | %7s | %8s | %s\n" \
            "$db" "$avg_ms" "$p50_ms" "$p95_ms" "$p99_ms" "$qps" "$success_mark"
    done

    echo ""
    log_separator
    echo "  結果保存先: ${RESULT_DIR}/"
    log_separator
}

# =============================================================================
# メイン関数
# =============================================================================
main() {
    # 結果ディレクトリ作成
    create_result_dir

    # 全体開始時刻
    local overall_start_epoch
    overall_start_epoch=$(date +%s)
    log_info "検索ベンチマーク開始"

    # Lambda invoke
    log_separator
    invoke_search_lambda
    log_separator

    # 各 DB の結果を個別 JSON に保存
    local response_file="${RESULT_DIR}/lambda-response.json"
    log_info "検索結果を個別ファイルに保存中..."

    save_db_result_json "aurora" "$response_file" || true
    save_db_result_json "opensearch" "$response_file" || true
    save_db_result_json "s3vectors" "$response_file" || true

    # 全体処理時間算出
    local overall_end_epoch total_duration_seconds
    overall_end_epoch=$(date +%s)
    total_duration_seconds=$((overall_end_epoch - overall_start_epoch))
    log_info "全体処理時間: ${total_duration_seconds} 秒"

    # サマリー JSON 生成
    generate_search_summary "$total_duration_seconds"

    # コンソールサマリー表示
    print_search_summary

    log_info "検索ベンチマークが完了しました。結果: ${RESULT_DIR}/"
}

# =============================================================================
# エントリポイント
# =============================================================================
parse_args "$@"
check_prerequisites
main
