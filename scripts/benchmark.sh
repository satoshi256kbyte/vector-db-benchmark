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
AURORA_SECRET_ARN=""

# Aurora 認証情報（get_aurora_credentials で設定）
AURORA_HOST=""
AURORA_PORT=""
AURORA_USER=""
AURORA_PASSWORD=""
AURORA_DBNAME=""

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
  --aurora-secret-arn ARN       Aurora Secrets Manager シークレット ARN
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
            --aurora-secret-arn)
                AURORA_SECRET_ARN="$2"
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
# Aurora ACU スケーリング
# =============================================================================

# Aurora Serverless v2 の最小 ACU を拡張する
scale_aurora_up() {
    log_info "Aurora ACU スケーリング: 最小 ACU を ${AURORA_MIN_ACU} に拡張します..."

    # 変更前の設定値をログ記録
    local current_config
    current_config=$(aws rds describe-db-clusters \
        --db-cluster-identifier "$AURORA_CLUSTER" \
        --query 'DBClusters[0].ServerlessV2ScalingConfiguration' \
        --output json \
        --region "$REGION")
    log_info "Aurora ACU 変更前: ${current_config}"

    # 最小 ACU を拡張
    if ! aws rds modify-db-cluster \
        --db-cluster-identifier "$AURORA_CLUSTER" \
        --serverless-v2-scaling-configuration \
        "MinCapacity=${AURORA_MIN_ACU},MaxCapacity=16" \
        --apply-immediately \
        --region "$REGION" > /dev/null; then
        log_error "Aurora ACU の拡張に失敗しました"
        return 1
    fi

    AURORA_SCALED_UP="true"
    log_info "Aurora ACU 拡張コマンドを実行しました（MinCapacity=${AURORA_MIN_ACU}, MaxCapacity=16）"

    # クラスターが available になるまで待機
    wait_aurora_available
}

# Aurora Serverless v2 の最小 ACU を元の値（0）に復元する
scale_aurora_down() {
    log_info "Aurora ACU スケーリング: 最小 ACU を 0 に復元します..."

    # 最小 ACU を 0 に復元
    if ! aws rds modify-db-cluster \
        --db-cluster-identifier "$AURORA_CLUSTER" \
        --serverless-v2-scaling-configuration \
        "MinCapacity=0,MaxCapacity=16" \
        --apply-immediately \
        --region "$REGION" > /dev/null; then
        log_error "Aurora ACU の復元に失敗しました"
        return 1
    fi

    AURORA_SCALED_UP="false"
    log_info "Aurora ACU 復元コマンドを実行しました（MinCapacity=0, MaxCapacity=16）"

    # クラスターが available になるまで待機
    wait_aurora_available

    # 変更後の設定値をログ記録
    local current_config
    current_config=$(aws rds describe-db-clusters \
        --db-cluster-identifier "$AURORA_CLUSTER" \
        --query 'DBClusters[0].ServerlessV2ScalingConfiguration' \
        --output json \
        --region "$REGION")
    log_info "Aurora ACU 変更後: ${current_config}"
}

# Aurora クラスターのステータスが available になるまでポーリングする
# 30秒間隔、最大20分（40回）
wait_aurora_available() {
    local max_attempts=40
    local interval=30
    local attempt=0

    log_info "Aurora クラスターが available になるまで待機中..."

    while [[ $attempt -lt $max_attempts ]]; do
        local status
        status=$(aws rds describe-db-clusters \
            --db-cluster-identifier "$AURORA_CLUSTER" \
            --query 'DBClusters[0].Status' \
            --output text \
            --region "$REGION")

        if [[ "$status" == "available" ]]; then
            log_info "Aurora クラスターが available になりました（${attempt} 回目のチェック）"
            return 0
        fi

        attempt=$((attempt + 1))
        log_info "Aurora クラスターのステータス: ${status}（${attempt}/${max_attempts} 回目、${interval}秒後に再チェック）"
        sleep "$interval"
    done

    log_error "Aurora クラスターが ${max_attempts} 回のチェック（最大 $((max_attempts * interval / 60)) 分）後も available になりませんでした"
    return 1
}

# =============================================================================
# OpenSearch OCU スケーリング
# =============================================================================

# OpenSearch Serverless の OCU 上限を拡張する
scale_opensearch_up() {
    log_info "OpenSearch OCU スケーリング: OCU 上限を ${OPENSEARCH_MAX_OCU} に拡張します..."

    # 変更前の設定値をログ記録
    local current_settings
    current_settings=$(aws opensearchserverless get-account-settings \
        --output json \
        --region "$REGION")
    log_info "OpenSearch OCU 変更前: ${current_settings}"

    # OCU 上限を拡張
    if ! aws opensearchserverless update-account-settings \
        --capacity-limits "maxIndexingCapacityInOCU=${OPENSEARCH_MAX_OCU},maxSearchCapacityInOCU=${OPENSEARCH_MAX_OCU}" \
        --region "$REGION" > /dev/null; then
        log_error "OpenSearch OCU の拡張に失敗しました"
        return 1
    fi

    OPENSEARCH_SCALED_UP="true"
    log_info "OpenSearch OCU 拡張コマンドを実行しました（maxIndexingCapacityInOCU=${OPENSEARCH_MAX_OCU}, maxSearchCapacityInOCU=${OPENSEARCH_MAX_OCU}）"

    # 変更後の設定値をログ記録
    local updated_settings
    updated_settings=$(aws opensearchserverless get-account-settings \
        --output json \
        --region "$REGION")
    log_info "OpenSearch OCU 変更後: ${updated_settings}"
}

# OpenSearch Serverless の OCU 上限を元の値（2）に復元する
scale_opensearch_down() {
    log_info "OpenSearch OCU スケーリング: OCU 上限を 2 に復元します..."

    # 変更前の設定値をログ記録
    local current_settings
    current_settings=$(aws opensearchserverless get-account-settings \
        --output json \
        --region "$REGION")
    log_info "OpenSearch OCU 復元前: ${current_settings}"

    # OCU 上限を 2 に復元
    if ! aws opensearchserverless update-account-settings \
        --capacity-limits "maxIndexingCapacityInOCU=2,maxSearchCapacityInOCU=2" \
        --region "$REGION" > /dev/null; then
        log_error "OpenSearch OCU の復元に失敗しました"
        return 1
    fi

    OPENSEARCH_SCALED_UP="false"
    log_info "OpenSearch OCU 復元コマンドを実行しました（maxIndexingCapacityInOCU=2, maxSearchCapacityInOCU=2）"

    # 変更後の設定値をログ記録
    local updated_settings
    updated_settings=$(aws opensearchserverless get-account-settings \
        --output json \
        --region "$REGION")
    log_info "OpenSearch OCU 復元後: ${updated_settings}"
}

# =============================================================================
# クリーンアップ処理
# =============================================================================
cleanup() {
    log_info "クリーンアップ処理を実行中..."

    # Aurora ACU を元に戻す
    if [[ "$AURORA_SCALED_UP" == "true" ]]; then
        log_info "Aurora ACU を元の値に戻しています..."
        aws rds modify-db-cluster \
            --db-cluster-identifier "$AURORA_CLUSTER" \
            --serverless-v2-scaling-configuration \
            "MinCapacity=0,MaxCapacity=16" \
            --apply-immediately \
            --region "$REGION" 2>/dev/null || true
    fi

    # OpenSearch OCU を元に戻す
    if [[ "$OPENSEARCH_SCALED_UP" == "true" ]]; then
        log_info "OpenSearch OCU を元の値に戻しています..."
        aws opensearchserverless update-account-settings \
            --capacity-limits "maxIndexingCapacityInOCU=2,maxSearchCapacityInOCU=2" \
            --region "$REGION" 2>/dev/null || true
    fi

    log_info "クリーンアップ完了"
}

trap cleanup EXIT

# =============================================================================
# Aurora インデックス操作
# =============================================================================

# Secrets Manager から Aurora 認証情報を取得する
get_aurora_credentials() {
    log_info "Secrets Manager から Aurora 認証情報を取得中..."

    local secret_json
    secret_json=$(aws secretsmanager get-secret-value \
        --secret-id "$AURORA_SECRET_ARN" \
        --query 'SecretString' --output text \
        --region "$REGION") || {
        log_error "Secrets Manager からの認証情報取得に失敗しました（ARN: ${AURORA_SECRET_ARN}）"
        return 1
    }

    if [[ -z "$secret_json" ]]; then
        log_error "Secrets Manager から空のシークレットが返されました（ARN: ${AURORA_SECRET_ARN}）"
        return 1
    fi

    AURORA_HOST=$(echo "$secret_json" | jq -r '.host')
    AURORA_PORT=$(echo "$secret_json" | jq -r '.port // 5432')
    AURORA_USER=$(echo "$secret_json" | jq -r '.username')
    AURORA_PASSWORD=$(echo "$secret_json" | jq -r '.password')
    AURORA_DBNAME=$(echo "$secret_json" | jq -r '.dbname // "postgres"')

    log_info "Aurora 認証情報を取得しました（host: ${AURORA_HOST}, port: ${AURORA_PORT}, dbname: ${AURORA_DBNAME}）"
}

# Aurora の HNSW インデックス削除 + テーブル TRUNCATE
drop_aurora_index() {
    log_info "Aurora インデックス削除 + TRUNCATE を実行中..."

    if ! PGPASSWORD="$AURORA_PASSWORD" psql \
        -h "$AURORA_HOST" -p "$AURORA_PORT" \
        -U "$AURORA_USER" -d "$AURORA_DBNAME" \
        -c "DROP INDEX IF EXISTS embeddings_hnsw_idx;" \
        -c "TRUNCATE TABLE embeddings;"; then
        log_error "Aurora インデックス削除 + TRUNCATE に失敗しました"
        return 1
    fi

    log_info "Aurora インデックス削除 + TRUNCATE が完了しました"
}

# Aurora の HNSW インデックスを再作成する
create_aurora_index() {
    log_info "Aurora HNSW インデックスを作成中..."

    if ! PGPASSWORD="$AURORA_PASSWORD" psql \
        -h "$AURORA_HOST" -p "$AURORA_PORT" \
        -U "$AURORA_USER" -d "$AURORA_DBNAME" \
        -c "CREATE INDEX embeddings_hnsw_idx ON embeddings \
            USING hnsw (embedding vector_cosine_ops) \
            WITH (m = 16, ef_construction = 64);"; then
        log_error "Aurora HNSW インデックスの作成に失敗しました"
        return 1
    fi

    log_info "Aurora HNSW インデックスの作成が完了しました"
}

# =============================================================================
# 後続タスクで追加される関数のプレースホルダー
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
