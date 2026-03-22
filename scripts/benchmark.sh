#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# ベンチマークシェルスクリプト
# 3つのベクトルDB（Aurora pgvector, OpenSearch Serverless, S3 Vectors）に対して
# データ投入ベンチマークを実行する
# =============================================================================

# =============================================================================
# デフォルト値
# =============================================================================
RECORD_COUNT=100000
AURORA_CLUSTER="vdbbench-dev-aurora-pgvector"
OPENSEARCH_COLLECTION="vdbbench-dev-oss-vector"
S3VECTORS_BUCKET="vdbbench-dev-s3vectors-benchmark"
ECS_CLUSTER="vdbbench-dev-ecs-benchmark"
REGION="ap-northeast-1"
AURORA_MIN_ACU=8
OPENSEARCH_MAX_OCU=10

# =============================================================================
# 状態フラグ（クリーンアップ用）
# =============================================================================
AURORA_SCALED_UP="false"
OPENSEARCH_SCALED_UP="false"

# =============================================================================
# プレースホルダー変数（後続タスクで設定）
# =============================================================================
TASK_DEFINITION=""

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

3つのベクトルDB（Aurora pgvector, OpenSearch Serverless, S3 Vectors）に対して
データ投入ベンチマークを実行する。

Options:
  --record-count N              投入レコード数 (デフォルト: 100000)
  --aurora-cluster ID           Aurora クラスター識別子 (デフォルト: vdbbench-dev-aurora-pgvector)
  --opensearch-collection NAME  OpenSearch コレクション名 (デフォルト: vdbbench-dev-oss-vector)
  --s3vectors-bucket NAME       S3 Vectors バケット名 (デフォルト: vdbbench-dev-s3vectors-benchmark)
  --ecs-cluster NAME            ECS クラスター名 (デフォルト: vdbbench-dev-ecs-benchmark)
  --region REGION               AWS リージョン (デフォルト: ap-northeast-1)
  --aurora-min-acu N            ACU 拡張時の最小値 (デフォルト: 8)
  --opensearch-max-ocu N        OCU 拡張時の上限値 (デフォルト: 10)
  --help                        ヘルプ表示
EOF
}

# =============================================================================
# 引数パース
# =============================================================================
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --record-count)
                RECORD_COUNT="$2"
                shift 2
                ;;
            --aurora-cluster)
                AURORA_CLUSTER="$2"
                shift 2
                ;;
            --opensearch-collection)
                OPENSEARCH_COLLECTION="$2"
                shift 2
                ;;
            --s3vectors-bucket)
                S3VECTORS_BUCKET="$2"
                shift 2
                ;;
            --ecs-cluster)
                ECS_CLUSTER="$2"
                shift 2
                ;;
            --region)
                REGION="$2"
                shift 2
                ;;
            --aurora-min-acu)
                AURORA_MIN_ACU="$2"
                shift 2
                ;;
            --opensearch-max-ocu)
                OPENSEARCH_MAX_OCU="$2"
                shift 2
                ;;
            --help)
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

    # psql の存在確認
    if ! command -v psql &>/dev/null; then
        log_error "psql がインストールされていません"
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

    log_info "前提条件チェック完了"
}

# =============================================================================
# 後続タスクで追加される関数のプレースホルダー
# - scale_aurora_up / scale_aurora_down / wait_aurora_available (Task 4.1)
# - scale_opensearch_up / scale_opensearch_down (Task 4.2)
# - cleanup + trap (Task 4.3)
# - get_aurora_credentials / drop_aurora_index / create_aurora_index (Task 5.1)
# - drop_opensearch_index / create_opensearch_index / run_ecs_task_with_mode (Task 5.2)
# - run_ecs_task (Task 5.3)
# - get_*_record_count (Task 6.1)
# - collect_task_logs / collect_aurora_metrics / calculate_fargate_cost (Task 6.2)
# - save_result_json / generate_summary (Task 6.3)
# - run_benchmark_cycle / main (Task 7.1)
# =============================================================================

# =============================================================================
# エントリポイント
# =============================================================================
parse_args "$@"
check_prerequisites
