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
SUBNET_IDS=""
SECURITY_GROUP_ID=""

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
  --task-definition ARN         ECS タスク定義 ARN
  --subnet-ids IDS              Fargate サブネット ID（カンマ区切り）
  --security-group-id ID        Fargate セキュリティグループ ID
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
            --task-definition)
                TASK_DEFINITION="$2"
                shift 2
                ;;
            --subnet-ids)
                SUBNET_IDS="$2"
                shift 2
                ;;
            --security-group-id)
                SECURITY_GROUP_ID="$2"
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

    # bc の存在確認
    if ! command -v bc &>/dev/null; then
        log_error "bc がインストールされていません"
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
# ECS タスクモード実行（OpenSearch インデックス操作用）
# =============================================================================

# ECS タスクを指定モードで起動し完了を待機する汎用関数
run_ecs_task_with_mode() {
    local target_db="$1"
    local task_mode="$2"
    local task_arn
    local exit_code

    log_info "ECS タスクを起動中（TARGET_DB=${target_db}, TASK_MODE=${task_mode}）..."

    task_arn=$(aws ecs run-task \
        --cluster "$ECS_CLUSTER" \
        --task-definition "$TASK_DEFINITION" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=DISABLED}" \
        --overrides '{
            "containerOverrides": [{
                "name": "BulkIngestContainer",
                "environment": [
                    {"name": "TARGET_DB", "value": "'"$target_db"'"},
                    {"name": "TASK_MODE", "value": "'"$task_mode"'"}
                ]
            }]
        }' \
        --query 'tasks[0].taskArn' --output text \
        --region "$REGION") || {
        log_error "ECS タスクの起動に失敗しました（TARGET_DB=${target_db}, TASK_MODE=${task_mode}）"
        return 1
    }

    if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
        log_error "ECS タスク ARN を取得できませんでした（TARGET_DB=${target_db}, TASK_MODE=${task_mode}）"
        return 1
    fi

    log_info "ECS タスクを起動しました: ${task_arn}"
    log_info "ECS タスクの完了を待機中..."

    aws ecs wait tasks-stopped \
        --cluster "$ECS_CLUSTER" \
        --tasks "$task_arn" \
        --region "$REGION" || {
        log_error "ECS タスクの待機に失敗しました: ${task_arn}"
        return 1
    }

    # 終了コード確認
    exit_code=$(aws ecs describe-tasks \
        --cluster "$ECS_CLUSTER" \
        --tasks "$task_arn" \
        --query 'tasks[0].containers[0].exitCode' --output text \
        --region "$REGION") || {
        log_error "ECS タスクの終了コード取得に失敗しました: ${task_arn}"
        return 1
    }

    if [[ "$exit_code" != "0" ]]; then
        local stop_reason
        stop_reason=$(aws ecs describe-tasks \
            --cluster "$ECS_CLUSTER" \
            --tasks "$task_arn" \
            --query 'tasks[0].stoppedReason' --output text \
            --region "$REGION" 2>/dev/null || echo "不明")
        log_error "ECS タスクが異常終了しました（終了コード: ${exit_code}, 理由: ${stop_reason}）"
        return 1
    fi

    log_info "ECS タスクが正常に完了しました（TARGET_DB=${target_db}, TASK_MODE=${task_mode}）"
}

# =============================================================================
# OpenSearch インデックス操作（ECS タスク経由）
# =============================================================================

# OpenSearch インデックスを削除する（ECS タスク経由）
drop_opensearch_index() {
    log_info "OpenSearch インデックス削除を開始します（ECS タスク経由）..."
    run_ecs_task_with_mode "opensearch" "index_drop"
}

# OpenSearch インデックスを作成する（ECS タスク経由）
create_opensearch_index() {
    log_info "OpenSearch インデックス作成を開始します（ECS タスク経由）..."
    run_ecs_task_with_mode "opensearch" "index_create"
}

# =============================================================================
# ECS タスク実行（データ投入）
# =============================================================================

# ECS タスクを起動しデータ投入を実行する
# グローバル変数 TASK_ARN, START_TIME, END_TIME, EXIT_CODE を設定する
run_ecs_task() {
    local target_db="$1"
    local record_count="$2"

    log_info "ECS データ投入タスクを起動中（TARGET_DB=${target_db}, RECORD_COUNT=${record_count}）..."

    START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    TASK_ARN=$(aws ecs run-task \
        --cluster "$ECS_CLUSTER" \
        --task-definition "$TASK_DEFINITION" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=DISABLED}" \
        --overrides '{
            "containerOverrides": [{
                "name": "BulkIngestContainer",
                "environment": [
                    {"name": "TARGET_DB", "value": "'"$target_db"'"},
                    {"name": "TASK_MODE", "value": "ingest"},
                    {"name": "RECORD_COUNT", "value": "'"$record_count"'"}
                ]
            }]
        }' \
        --query 'tasks[0].taskArn' --output text \
        --region "$REGION") || {
        log_error "ECS データ投入タスクの起動に失敗しました（TARGET_DB=${target_db}）"
        return 1
    }

    if [[ -z "$TASK_ARN" || "$TASK_ARN" == "None" ]]; then
        log_error "ECS タスク ARN を取得できませんでした（TARGET_DB=${target_db}）"
        return 1
    fi

    log_info "ECS データ投入タスクを起動しました: ${TASK_ARN}"
    log_info "ECS タスクの完了を待機中..."

    aws ecs wait tasks-stopped \
        --cluster "$ECS_CLUSTER" \
        --tasks "$TASK_ARN" \
        --region "$REGION" || {
        log_error "ECS タスクの待機に失敗しました: ${TASK_ARN}"
        return 1
    }

    END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # 終了コード確認
    EXIT_CODE=$(aws ecs describe-tasks \
        --cluster "$ECS_CLUSTER" \
        --tasks "$TASK_ARN" \
        --query 'tasks[0].containers[0].exitCode' --output text \
        --region "$REGION") || {
        log_error "ECS タスクの終了コード取得に失敗しました: ${TASK_ARN}"
        return 1
    }

    if [[ "$EXIT_CODE" != "0" ]]; then
        local stop_reason
        stop_reason=$(aws ecs describe-tasks \
            --cluster "$ECS_CLUSTER" \
            --tasks "$TASK_ARN" \
            --query 'tasks[0].stoppedReason' --output text \
            --region "$REGION" 2>/dev/null || echo "不明")
        log_error "ECS データ投入タスクが異常終了しました（終了コード: ${EXIT_CODE}, 理由: ${stop_reason}）"
        return 1
    fi

    log_info "ECS データ投入タスクが正常に完了しました（TARGET_DB=${target_db}, 開始: ${START_TIME}, 終了: ${END_TIME}）"
}

# =============================================================================
# レコード数取得
# =============================================================================

# Aurora のレコード数を psql 経由で取得する
get_aurora_record_count() {
    PGPASSWORD="$AURORA_PASSWORD" psql \
        -h "$AURORA_HOST" -p "$AURORA_PORT" \
        -U "$AURORA_USER" -d "$AURORA_DBNAME" \
        -t -A -c "SELECT COUNT(*) FROM embeddings;" 2>/dev/null || echo "0"
}

# OpenSearch のレコード数を取得する
# 設計判断: OpenSearch Serverless は VPC 内からのみアクセス可能なため、
# 直接カウントできない。投入前は 0（TRUNCATE/インデックス削除後）、
# 投入後は RECORD_COUNT を返す。
get_opensearch_record_count() {
    echo "$RECORD_COUNT"
}

# S3 Vectors のレコード数を AWS CLI 経由で取得する
get_s3vectors_record_count() {
    aws s3vectors list-vectors \
        --vector-bucket-name "$S3VECTORS_BUCKET" \
        --index-name "embeddings" \
        --query 'vectors | length(@)' --output text \
        --region "$REGION" 2>/dev/null || echo "0"
}

# =============================================================================
# ログ収集・メトリクス取得・コスト算出
# =============================================================================

# CloudWatch Logs から ECS タスクのログを収集しファイルに保存する
# グローバル変数 TASK_ARN からタスク ID を抽出してログストリームをフィルタする
collect_task_logs() {
    local target_db="$1"
    local result_dir="$2"
    local log_group="/ecs/${ECS_CLUSTER}"
    local log_file="${result_dir}/${target_db}-task.log"

    log_info "CloudWatch Logs からタスクログを収集中（${target_db}）..."

    # TASK_ARN からタスク ID を抽出（例: arn:aws:ecs:region:account:task/cluster/TASK_ID）
    local task_id
    task_id=$(echo "$TASK_ARN" | awk -F'/' '{print $NF}')

    if [[ -z "$task_id" ]]; then
        log_error "タスク ID を TASK_ARN から抽出できませんでした: ${TASK_ARN}"
        return 1
    fi

    log_info "タスク ID: ${task_id}, ロググループ: ${log_group}"

    # タスク ID を含むログストリームを検索
    local log_streams
    log_streams=$(aws logs describe-log-streams \
        --log-group-name "$log_group" \
        --log-stream-name-prefix "ecs/BulkIngestContainer/${task_id}" \
        --query 'logStreams[*].logStreamName' --output json \
        --region "$REGION" 2>/dev/null) || {
        log_error "ログストリームの検索に失敗しました（ロググループ: ${log_group}）"
        return 1
    }

    local stream_count
    stream_count=$(echo "$log_streams" | jq 'length')

    if [[ "$stream_count" -eq 0 ]]; then
        log_error "該当するログストリームが見つかりませんでした（タスク ID: ${task_id}）"
        return 1
    fi

    # 各ログストリームからログイベントを取得してファイルに保存
    > "$log_file"
    local stream_name
    for stream_name in $(echo "$log_streams" | jq -r '.[]'); do
        aws logs get-log-events \
            --log-group-name "$log_group" \
            --log-stream-name "$stream_name" \
            --start-from-head \
            --query 'events[*].message' --output text \
            --region "$REGION" >> "$log_file" 2>/dev/null || {
            log_error "ログイベントの取得に失敗しました（ストリーム: ${stream_name}）"
            continue
        }
    done

    log_info "タスクログを保存しました: ${log_file}"
}

# CloudWatch メトリクスから Aurora Serverless v2 の ACU 値を取得する
# グローバル変数 START_TIME, END_TIME を使用してメトリクス期間を指定する
collect_aurora_metrics() {
    log_info "Aurora ACU メトリクスを取得中..."

    local metric_json
    metric_json=$(aws cloudwatch get-metric-data \
        --metric-data-queries '[
            {
                "Id": "acu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/RDS",
                        "MetricName": "ServerlessDatabaseCapacity",
                        "Dimensions": [
                            {
                                "Name": "DBClusterIdentifier",
                                "Value": "'"$AURORA_CLUSTER"'"
                            }
                        ]
                    },
                    "Period": 60,
                    "Stat": "Maximum"
                },
                "ReturnData": true
            }
        ]' \
        --start-time "$START_TIME" \
        --end-time "$END_TIME" \
        --region "$REGION" 2>/dev/null) || {
        log_error "Aurora ACU メトリクスの取得に失敗しました"
        echo "0"
        return 0
    }

    local acu_value
    acu_value=$(echo "$metric_json" | jq -r '.MetricDataResults[0].Values | max // 0')

    if [[ -z "$acu_value" || "$acu_value" == "null" ]]; then
        acu_value="0"
    fi

    log_info "Aurora ACU ピーク値: ${acu_value}"
    echo "$acu_value"
}

# Fargate 概算コストを算出する（ap-northeast-1 料金）
# vCPU: $0.05056/時間, メモリ: $0.00553/GB/時間
calculate_fargate_cost() {
    local duration_seconds="$1"
    local vcpu=2
    local memory_gb=4
    local hours
    hours=$(echo "scale=6; $duration_seconds / 3600" | bc)
    local vcpu_cost
    vcpu_cost=$(echo "scale=6; $hours * $vcpu * 0.05056" | bc)
    local memory_cost
    memory_cost=$(echo "scale=6; $hours * $memory_gb * 0.00553" | bc)
    echo "scale=4; $vcpu_cost + $memory_cost" | bc
}

# =============================================================================
# 後続タスクで追加される関数のプレースホルダー
# - save_result_json / generate_summary (Task 6.3)
# - run_benchmark_cycle / main (Task 7.1)
# =============================================================================

# =============================================================================
# エントリポイント
# =============================================================================
parse_args "$@"
check_prerequisites
