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

# =============================================================================
# プレースホルダー変数（後続タスクで設定）
# =============================================================================
TASK_DEFINITION=""
AURORA_SECRET_ARN=""
SUBNET_IDS=""
SECURITY_GROUP_ID=""

# CloudWatch Logs ロググループ名
ECS_LOG_GROUP=""

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
  --ecs-log-group NAME          ECS タスクの CloudWatch Logs ロググループ名
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
            --ecs-log-group)
                ECS_LOG_GROUP="$2"
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
# クリーンアップ処理
# =============================================================================
cleanup() {
    log_info "クリーンアップ処理を実行中..."
    log_info "クリーンアップ完了"
}

trap cleanup EXIT

# =============================================================================
# Aurora インデックス操作（ECS タスク経由）
# =============================================================================

# Aurora の HNSW インデックス削除 + テーブル TRUNCATE（ECS タスク経由）
drop_aurora_index() {
    log_info "Aurora インデックス削除を開始します（ECS タスク経由）..."
    run_ecs_task_with_mode "aurora" "index_drop"
}

# Aurora の HNSW インデックスを再作成する（ECS タスク経由）
create_aurora_index() {
    log_info "Aurora HNSW インデックス作成を開始します（ECS タスク経由）..."
    run_ecs_task_with_mode "aurora" "index_create"
}

# =============================================================================
# ECS タスクモード実行（OpenSearch インデックス操作用）
# =============================================================================

# ECS タスクを指定モードで起動し完了を待機する汎用関数
# 戻り値: 成功時 0、失敗時 1
# count モードの場合、グローバル変数 ECS_COUNT_RESULT にレコード数を設定する
ECS_COUNT_RESULT=0
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

    # count モードの場合、CloudWatch Logs からレコード数を取得
    if [[ "$task_mode" == "count" ]]; then
        _extract_record_count_from_logs "$task_arn"
    fi
}

# CloudWatch Logs から RECORD_COUNT_RESULT:N を抽出する
_extract_record_count_from_logs() {
    local task_arn="$1"
    local task_id
    task_id=$(echo "$task_arn" | awk -F'/' '{print $NF}')

    local log_group="${ECS_LOG_GROUP:-vdbbench-dev-cloudwatch-ecs-bulk-ingest}"

    # ログストリーム名を検索（プレフィックスは bulk-ingest/BulkIngestContainer/タスクID）
    local log_streams
    log_streams=$(aws logs describe-log-streams \
        --log-group-name "$log_group" \
        --log-stream-name-prefix "bulk-ingest/BulkIngestContainer/${task_id}" \
        --query 'logStreams[*].logStreamName' --output json \
        --region "$REGION" 2>/dev/null || echo "[]")

    local stream_count
    stream_count=$(echo "$log_streams" | jq 'length')

    if [[ "$stream_count" -eq 0 ]]; then
        ECS_COUNT_RESULT=0
        log_error "レコード数取得用のログストリームが見つかりませんでした（タスク ID: ${task_id}）"
        return
    fi

    # 最初のログストリームからログイベントを取得
    local stream_name
    stream_name=$(echo "$log_streams" | jq -r '.[0]')

    local log_output
    log_output=$(aws logs get-log-events \
        --log-group-name "$log_group" \
        --log-stream-name "$stream_name" \
        --start-from-head \
        --query 'events[*].message' --output text \
        --region "$REGION" 2>/dev/null || echo "")

    # RECORD_COUNT_RESULT:N パターンを抽出
    local count_line
    count_line=$(echo "$log_output" | grep -o 'RECORD_COUNT_RESULT:[0-9]*' | head -1 || echo "")

    if [[ -n "$count_line" ]]; then
        ECS_COUNT_RESULT=$(echo "$count_line" | cut -d':' -f2)
        log_info "ECS タスクからレコード数を取得: ${ECS_COUNT_RESULT}"
    else
        ECS_COUNT_RESULT=0
        log_error "ECS タスクログからレコード数を取得できませんでした"
    fi
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
# レコード数取得（ECS タスク経由）
# =============================================================================

# 指定 DB のレコード数を ECS タスク経由で取得する
# 結果はグローバル変数 ECS_COUNT_RESULT に設定される
get_record_count() {
    local target_db="$1"
    log_info "${target_db} のレコード数を取得中（ECS タスク経由）..."

    if run_ecs_task_with_mode "$target_db" "count"; then
        echo "$ECS_COUNT_RESULT"
    else
        log_error "${target_db} のレコード数取得に失敗しました"
        echo "0"
    fi
}

# =============================================================================
# ログ収集・メトリクス取得・コスト算出
# =============================================================================

# CloudWatch Logs から ECS タスクのログを収集しファイルに保存する
# グローバル変数 TASK_ARN からタスク ID を抽出してログストリームをフィルタする
collect_task_logs() {
    local target_db="$1"
    local result_dir="$2"
    local log_group="${ECS_LOG_GROUP:-vdbbench-dev-cloudwatch-ecs-bulk-ingest}"
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
        --log-stream-name-prefix "bulk-ingest/BulkIngestContainer/${task_id}" \
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
# ピーク値を stdout に出力し、時系列データを RESULT_DIR/aurora-acu-timeseries.json に保存する
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

    # 時系列データを JSON ファイルに保存
    echo "$metric_json" | jq '{
        metric: "ServerlessDatabaseCapacity",
        cluster: "'"$AURORA_CLUSTER"'",
        start_time: "'"$START_TIME"'",
        end_time: "'"$END_TIME"'",
        period_seconds: 60,
        timestamps: .MetricDataResults[0].Timestamps,
        values: .MetricDataResults[0].Values,
        peak: (.MetricDataResults[0].Values | max // 0)
    }' > "${RESULT_DIR}/aurora-acu-timeseries.json" 2>/dev/null || true

    log_info "Aurora ACU ピーク値: ${acu_value}"
    echo "$acu_value"
}

# CloudWatch メトリクスから OpenSearch Serverless の OCU 値を取得する
# グローバル変数 START_TIME, END_TIME を使用してメトリクス期間を指定する
# ピーク OCU（Indexing + Search の合計ピーク）を stdout に出力し、
# 時系列データを RESULT_DIR/opensearch-ocu-timeseries.json に保存する
collect_opensearch_metrics() {
    log_info "OpenSearch OCU メトリクスを取得中..."

    local metric_json
    metric_json=$(aws cloudwatch get-metric-data \
        --metric-data-queries '[
            {
                "Id": "indexing_ocu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/AOSS",
                        "MetricName": "IndexingOCU",
                        "Dimensions": [
                            {
                                "Name": "CollectionName",
                                "Value": "'"$OPENSEARCH_COLLECTION"'"
                            }
                        ]
                    },
                    "Period": 60,
                    "Stat": "Maximum"
                },
                "ReturnData": true
            },
            {
                "Id": "search_ocu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/AOSS",
                        "MetricName": "SearchOCU",
                        "Dimensions": [
                            {
                                "Name": "CollectionName",
                                "Value": "'"$OPENSEARCH_COLLECTION"'"
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
        log_error "OpenSearch OCU メトリクスの取得に失敗しました"
        echo "0"
        return 0
    }

    local indexing_peak search_peak total_peak
    indexing_peak=$(echo "$metric_json" | jq -r '[.MetricDataResults[] | select(.Id == "indexing_ocu")] | .[0].Values | max // 0')
    search_peak=$(echo "$metric_json" | jq -r '[.MetricDataResults[] | select(.Id == "search_ocu")] | .[0].Values | max // 0')
    total_peak=$(echo "scale=2; ${indexing_peak:-0} + ${search_peak:-0}" | bc)

    # 時系列データを JSON ファイルに保存
    echo "$metric_json" | jq '{
        collection: "'"$OPENSEARCH_COLLECTION"'",
        start_time: "'"$START_TIME"'",
        end_time: "'"$END_TIME"'",
        period_seconds: 60,
        indexing_ocu: {
            timestamps: ([.MetricDataResults[] | select(.Id == "indexing_ocu")] | .[0].Timestamps),
            values: ([.MetricDataResults[] | select(.Id == "indexing_ocu")] | .[0].Values),
            peak: ([.MetricDataResults[] | select(.Id == "indexing_ocu")] | .[0].Values | max // 0)
        },
        search_ocu: {
            timestamps: ([.MetricDataResults[] | select(.Id == "search_ocu")] | .[0].Timestamps),
            values: ([.MetricDataResults[] | select(.Id == "search_ocu")] | .[0].Values),
            peak: ([.MetricDataResults[] | select(.Id == "search_ocu")] | .[0].Values | max // 0)
        }
    }' > "${RESULT_DIR}/opensearch-ocu-timeseries.json" 2>/dev/null || true

    log_info "OpenSearch OCU ピーク値: indexing=${indexing_peak}, search=${search_peak}, total=${total_peak}"
    echo "$total_peak"
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

# Aurora Serverless v2 ACU 概算コストを算出する（ap-northeast-1 料金）
# ACU 単価: $0.12/ACU/時間
calculate_aurora_acu_cost() {
    local acu_peak="$1"
    local duration_seconds="$2"
    local hours
    hours=$(echo "scale=6; $duration_seconds / 3600" | bc)
    echo "scale=4; $hours * $acu_peak * 0.12" | bc
}

# OpenSearch Serverless OCU 概算コストを算出する（ap-northeast-1 料金）
# OCU 単価: $0.24/OCU/時間
calculate_opensearch_ocu_cost() {
    local ocu_peak="$1"
    local duration_seconds="$2"
    local hours
    hours=$(echo "scale=6; $duration_seconds / 3600" | bc)
    echo "scale=4; $hours * $ocu_peak * 0.24" | bc
}

# S3 Vectors 概算コストを算出する（ap-northeast-1 料金）
# Put bytes: $0.219/GB, Storage: $0.066/GB-Mo（ベンチマーク中のストレージは無視可能）
# ベンチマークでは PUT バイト数が主要コストドライバー
# 1レコード = 1536次元 × 4バイト(float32) ≈ 6144バイト（メタデータ含め約 6.5KB と推定）
calculate_s3vectors_cost() {
    local record_count="$1"
    local bytes_per_record=6656  # 1536 * 4 + 512 (メタデータ推定)
    local total_bytes
    total_bytes=$(echo "$record_count * $bytes_per_record" | bc)
    local total_gb
    total_gb=$(echo "scale=6; $total_bytes / 1073741824" | bc)
    echo "scale=4; $total_gb * 0.219" | bc
}

# =============================================================================
# 結果ディレクトリ作成
# =============================================================================

# ベンチマーク結果ディレクトリを作成し、グローバル変数 RESULT_DIR に設定する
RESULT_DIR=""
BENCHMARK_ID=""

create_result_dir() {
    BENCHMARK_ID=$(date -u +"%Y%m%d-%H%M%S")
    RESULT_DIR="results/${BENCHMARK_ID}"

    mkdir -p "$RESULT_DIR"
    log_info "結果ディレクトリを作成しました: ${RESULT_DIR}"
}

# =============================================================================
# 個別 DB 結果 JSON 生成・保存
# =============================================================================

# 個別 DB の結果 JSON を生成しファイルに保存する
# 引数:
#   $1  - database: DB 識別名（aurora_pgvector, opensearch, s3vectors）
#   $2  - record_count: 投入レコード数
#   $3  - pre_count: 投入前レコード数
#   $4  - post_count: 投入後レコード数
#   $5  - start_time: 開始時刻（ISO 8601）
#   $6  - end_time: 終了時刻（ISO 8601）
#   $7  - duration_seconds: データ投入処理時間（秒）
#   $8  - index_drop_success: インデックス削除成功フラグ（true/false）
#   $9  - index_create_success: インデックス作成成功フラグ（true/false）
#   $10 - ecs_task_arn: ECS タスク ARN
#   $11 - ecs_exit_code: ECS タスク終了コード
#   $12 - acu_before: ACU 変更前値
#   $13 - acu_during: ACU ピーク値
#   $14 - acu_after: ACU 変更後値
#   $15 - success: 成功フラグ（true/false）
#   $16 - error_message: エラーメッセージ（なければ null）
#   $17 - fargate_cost_usd: Fargate 概算コスト（USD）
#   $18 - opensearch_ocu_peak: OpenSearch OCU ピーク値
#   $19 - index_create_duration_seconds: インデックス作成時間（秒、Aurora のみ）
#   $20 - service_cost_usd: サービス概算コスト（Aurora ACU / OpenSearch OCU）
save_result_json() {
    local database="$1"
    local record_count="$2"
    local pre_count="$3"
    local post_count="$4"
    local start_time="$5"
    local end_time="$6"
    local duration_seconds="$7"
    local index_drop_success="$8"
    local index_create_success="$9"
    local ecs_task_arn="${10}"
    local ecs_exit_code="${11}"
    local acu_before="${12}"
    local acu_during="${13}"
    local acu_after="${14}"
    local success="${15}"
    local error_message="${16}"
    local fargate_cost_usd="${17:-0}"
    local opensearch_ocu_peak="${18:-0}"
    local index_create_duration_seconds="${19:-0}"
    local service_cost_usd="${20:-0}"

    # スループット算出（duration_seconds が 0 の場合は 0）
    local throughput="0"
    if [[ "$duration_seconds" -gt 0 ]]; then
        throughput=$(echo "scale=2; $record_count / $duration_seconds" | bc)
    fi

    # DB 識別名からファイル名を決定（aurora_pgvector → aurora, opensearch → opensearch, s3vectors → s3vectors）
    local file_prefix
    case "$database" in
        aurora_pgvector) file_prefix="aurora" ;;
        opensearch)      file_prefix="opensearch" ;;
        s3vectors)       file_prefix="s3vectors" ;;
        *)               file_prefix="$database" ;;
    esac

    local output_file="${RESULT_DIR}/${file_prefix}-result.json"

    # jq で JSON を生成（proper escaping と null 処理）
    jq -n \
        --arg database "$database" \
        --argjson record_count "$record_count" \
        --argjson pre_count "$pre_count" \
        --argjson post_count "$post_count" \
        --arg start_time "$start_time" \
        --arg end_time "$end_time" \
        --argjson duration_seconds "$duration_seconds" \
        --argjson throughput "$throughput" \
        --argjson index_drop_success "$index_drop_success" \
        --argjson index_create_success "$index_create_success" \
        --arg ecs_task_arn "$ecs_task_arn" \
        --argjson ecs_exit_code "$ecs_exit_code" \
        --argjson acu_before "$acu_before" \
        --argjson acu_during "$acu_during" \
        --argjson acu_after "$acu_after" \
        --argjson success "$success" \
        --arg error_message "$error_message" \
        --argjson fargate_cost_usd "$fargate_cost_usd" \
        --argjson opensearch_ocu_peak "$opensearch_ocu_peak" \
        --argjson index_create_duration_seconds "$index_create_duration_seconds" \
        --argjson service_cost_usd "$service_cost_usd" \
        '{
            database: $database,
            record_count: $record_count,
            pre_count: $pre_count,
            post_count: $post_count,
            start_time: $start_time,
            end_time: $end_time,
            duration_seconds: $duration_seconds,
            throughput_records_per_sec: $throughput,
            index_drop_success: $index_drop_success,
            index_create_success: $index_create_success,
            ecs_task_arn: $ecs_task_arn,
            ecs_exit_code: $ecs_exit_code,
            acu_before: $acu_before,
            acu_during: $acu_during,
            acu_after: $acu_after,
            fargate_cost_usd: $fargate_cost_usd,
            opensearch_ocu_peak: $opensearch_ocu_peak,
            index_create_duration_seconds: $index_create_duration_seconds,
            service_cost_usd: $service_cost_usd,
            success: $success,
            error_message: (if $error_message == "" then null else $error_message end)
        }' > "$output_file"

    log_info "結果 JSON を保存しました: ${output_file}"
}

# =============================================================================
# サマリー JSON 生成
# =============================================================================

# 全 DB の結果を統合したサマリー JSON を生成する
# 引数:
#   $1 - total_duration_seconds: 全体の処理時間（秒）
#   $2 - fargate_total_seconds: Fargate 合計実行時間（秒）
#   $3 - fargate_estimated_cost_usd: Fargate 概算コスト（USD）
#   $4 - aurora_acu_peak: Aurora ACU ピーク値
#   $5 - opensearch_ocu_peak: OpenSearch OCU ピーク値
#   $6 - aurora_service_cost_usd: Aurora ACU 概算コスト（USD）
#   $7 - opensearch_service_cost_usd: OpenSearch OCU 概算コスト（USD）
#   $8 - s3vectors_service_cost_usd: S3 Vectors 概算コスト（USD）
generate_summary() {
    local total_duration_seconds="$1"
    local fargate_total_seconds="$2"
    local fargate_estimated_cost_usd="$3"
    local aurora_acu_peak="$4"
    local opensearch_ocu_peak="$5"
    local aurora_service_cost_usd="${6:-0}"
    local opensearch_service_cost_usd="${7:-0}"
    local s3vectors_service_cost_usd="${8:-0}"

    local completed_at
    completed_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local output_file="${RESULT_DIR}/summary.json"

    # 各 DB の結果 JSON を読み込んで results オブジェクトを構築
    local aurora_result="{}"
    local opensearch_result="{}"
    local s3vectors_result="{}"

    if [[ -f "${RESULT_DIR}/aurora-result.json" ]]; then
        aurora_result=$(jq '{
            duration_seconds: .duration_seconds,
            throughput_records_per_sec: .throughput_records_per_sec,
            pre_count: .pre_count,
            post_count: .post_count,
            index_create_duration_seconds: .index_create_duration_seconds,
            service_cost_usd: .service_cost_usd,
            success: .success
        }' "${RESULT_DIR}/aurora-result.json")
    fi

    if [[ -f "${RESULT_DIR}/opensearch-result.json" ]]; then
        opensearch_result=$(jq '{
            duration_seconds: .duration_seconds,
            throughput_records_per_sec: .throughput_records_per_sec,
            pre_count: .pre_count,
            post_count: .post_count,
            opensearch_ocu_peak: .opensearch_ocu_peak,
            service_cost_usd: .service_cost_usd,
            success: .success
        }' "${RESULT_DIR}/opensearch-result.json")
    fi

    if [[ -f "${RESULT_DIR}/s3vectors-result.json" ]]; then
        s3vectors_result=$(jq '{
            duration_seconds: .duration_seconds,
            throughput_records_per_sec: .throughput_records_per_sec,
            pre_count: .pre_count,
            post_count: .post_count,
            service_cost_usd: .service_cost_usd,
            success: .success
        }' "${RESULT_DIR}/s3vectors-result.json")
    fi

    # jq でサマリー JSON を生成
    jq -n \
        --arg benchmark_id "$BENCHMARK_ID" \
        --arg region "$REGION" \
        --argjson record_count "$RECORD_COUNT" \
        --argjson vector_dimension 1536 \
        --argjson aurora_result "$aurora_result" \
        --argjson opensearch_result "$opensearch_result" \
        --argjson s3vectors_result "$s3vectors_result" \
        --argjson aurora_acu_peak "$aurora_acu_peak" \
        --argjson opensearch_ocu_peak "$opensearch_ocu_peak" \
        --argjson aurora_service_cost_usd "$aurora_service_cost_usd" \
        --argjson opensearch_service_cost_usd "$opensearch_service_cost_usd" \
        --argjson s3vectors_service_cost_usd "$s3vectors_service_cost_usd" \
        --argjson fargate_total_seconds "$fargate_total_seconds" \
        --argjson fargate_vcpu 2 \
        --argjson fargate_memory_gb 4 \
        --argjson fargate_estimated_cost_usd "$fargate_estimated_cost_usd" \
        --argjson total_duration_seconds "$total_duration_seconds" \
        --arg completed_at "$completed_at" \
        '{
            benchmark_id: $benchmark_id,
            region: $region,
            record_count: $record_count,
            vector_dimension: $vector_dimension,
            results: {
                aurora_pgvector: $aurora_result,
                opensearch: $opensearch_result,
                s3vectors: $s3vectors_result
            },
            cost_summary: {
                aurora_acu_peak: $aurora_acu_peak,
                aurora_acu_cost_usd: $aurora_service_cost_usd,
                opensearch_ocu_peak: $opensearch_ocu_peak,
                opensearch_ocu_cost_usd: $opensearch_service_cost_usd,
                s3vectors_cost_usd: $s3vectors_service_cost_usd,
                fargate_total_seconds: $fargate_total_seconds,
                fargate_vcpu: $fargate_vcpu,
                fargate_memory_gb: $fargate_memory_gb,
                fargate_estimated_cost_usd: $fargate_estimated_cost_usd
            },
            total_duration_seconds: $total_duration_seconds,
            completed_at: $completed_at
        }' > "$output_file"

    log_info "サマリー JSON を保存しました: ${output_file}"
}

# =============================================================================
# サマリーコンソール表示
# =============================================================================

# サマリー JSON の内容をコンソールに表示する
print_summary() {
    local summary_file="${RESULT_DIR}/summary.json"

    if [[ ! -f "$summary_file" ]]; then
        log_error "サマリーファイルが見つかりません: ${summary_file}"
        return 1
    fi

    log_separator
    echo ""
    echo "  ベンチマーク結果サマリー"
    echo "  Benchmark ID: $(jq -r '.benchmark_id' "$summary_file")"
    echo "  Region: $(jq -r '.region' "$summary_file")"
    echo "  Record Count: $(jq -r '.record_count' "$summary_file")"
    echo ""
    log_separator

    # 各 DB の結果を表示
    local dbs=("aurora_pgvector" "opensearch" "s3vectors")
    for db in "${dbs[@]}"; do
        local success
        success=$(jq -r ".results.${db}.success // \"N/A\"" "$summary_file")
        local duration
        duration=$(jq -r ".results.${db}.duration_seconds // \"N/A\"" "$summary_file")
        local throughput
        throughput=$(jq -r ".results.${db}.throughput_records_per_sec // \"N/A\"" "$summary_file")
        local post_count
        post_count=$(jq -r ".results.${db}.post_count // \"N/A\"" "$summary_file")

        printf "  %-20s | success: %-5s | duration: %6s sec | throughput: %8s rec/sec | records: %s\n" \
            "$db" "$success" "$duration" "$throughput" "$post_count"
    done

    echo ""
    log_separator

    # コストサマリー表示
    echo "  コストサマリー（DB サービス）:"
    echo "    Aurora ACU peak:          $(jq -r '.cost_summary.aurora_acu_peak' "$summary_file")"
    echo "    Aurora ACU cost:          \$$(jq -r '.cost_summary.aurora_acu_cost_usd' "$summary_file")"
    echo "    OpenSearch OCU peak:      $(jq -r '.cost_summary.opensearch_ocu_peak' "$summary_file")"
    echo "    OpenSearch OCU cost:      \$$(jq -r '.cost_summary.opensearch_ocu_cost_usd' "$summary_file")"
    echo "    S3 Vectors cost:          \$$(jq -r '.cost_summary.s3vectors_cost_usd' "$summary_file")"
    echo ""
    echo "  コストサマリー（Fargate）:"
    echo "    Fargate total seconds:    $(jq -r '.cost_summary.fargate_total_seconds' "$summary_file")"
    echo "    Fargate estimated cost:   \$$(jq -r '.cost_summary.fargate_estimated_cost_usd' "$summary_file")"
    echo ""
    echo "  Total duration: $(jq -r '.total_duration_seconds' "$summary_file") seconds"
    echo "  Completed at:   $(jq -r '.completed_at' "$summary_file")"
    echo "  Results dir:    ${RESULT_DIR}/"
    echo ""
    log_separator
}

# =============================================================================
# ベンチマークサイクル実行
# =============================================================================

# 1つの DB に対するベンチマークサイクル全体を実行する
# 引数:
#   $1 - target_db: DB 識別名（aurora, opensearch, s3vectors）
run_benchmark_cycle() {
    local target_db="$1"
    local db_label=""
    local cycle_success="true"
    local cycle_error=""
    local pre_count=0
    local post_count=0
    local acu_before=0
    local acu_during=0
    local acu_after=0
    local index_drop_success="false"
    local index_create_success="false"
    local duration_seconds=0

    case "$target_db" in
        aurora)      db_label="aurora_pgvector" ;;
        opensearch)  db_label="opensearch" ;;
        s3vectors)   db_label="s3vectors" ;;
        *)
            log_error "不明な target_db: ${target_db}"
            return 1
            ;;
    esac

    log_info "===== ${db_label} ベンチマークサイクル開始 ====="

    # --- Step 1: 投入前レコード数取得 ---
    pre_count=$(get_record_count "$target_db")
    log_info "${db_label} 投入前レコード数: ${pre_count}"

    # --- Step 2: インデックス削除（Aurora のみ） ---
    case "$target_db" in
        aurora)
            if drop_aurora_index; then
                index_drop_success="true"
            else
                cycle_success="false"
                cycle_error="Aurora インデックス削除に失敗"
                log_error "$cycle_error"
                save_result_json "$db_label" "$RECORD_COUNT" "$pre_count" "$post_count" \
                    "" "" "$duration_seconds" "$index_drop_success" "$index_create_success" \
                    "" "0" "$acu_before" "$acu_during" "$acu_after" "$cycle_success" "$cycle_error"
                return 0
            fi
            ;;
        opensearch|s3vectors)
            log_info "${db_label}: インデックス削除はスキップ"
            index_drop_success="true"
            ;;
    esac

    # --- Step 3: ECS タスク実行（データ投入） ---
    if ! run_ecs_task "$target_db" "$RECORD_COUNT"; then
        cycle_success="false"
        cycle_error="ECS データ投入タスクが失敗（target_db=${target_db}）"
        log_error "$cycle_error"
        save_result_json "$db_label" "$RECORD_COUNT" "$pre_count" "$post_count" \
            "${START_TIME:-}" "${END_TIME:-}" "$duration_seconds" "$index_drop_success" "$index_create_success" \
            "${TASK_ARN:-}" "${EXIT_CODE:-1}" "$acu_before" "$acu_during" "$acu_after" "$cycle_success" "$cycle_error"
        return 0
    fi

    # 処理時間算出
    local start_epoch end_epoch
    start_epoch=$(date -d "$START_TIME" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$START_TIME" +%s 2>/dev/null || echo "0")
    end_epoch=$(date -d "$END_TIME" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$END_TIME" +%s 2>/dev/null || echo "0")
    if [[ "$start_epoch" -gt 0 && "$end_epoch" -gt 0 ]]; then
        duration_seconds=$((end_epoch - start_epoch))
    fi
    log_info "${db_label} 処理時間: ${duration_seconds} 秒"

    # Fargate 合計秒数を加算
    fargate_total_seconds=$((fargate_total_seconds + duration_seconds))

    # --- Step 4: インデックス作成（Aurora のみ、タイミング計測付き） ---
    local index_create_duration_seconds=0
    case "$target_db" in
        aurora)
            local idx_start idx_end idx_start_epoch idx_end_epoch
            idx_start=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
            if create_aurora_index; then
                index_create_success="true"
                idx_end=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
                idx_start_epoch=$(date -d "$idx_start" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$idx_start" +%s 2>/dev/null || echo "0")
                idx_end_epoch=$(date -d "$idx_end" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$idx_end" +%s 2>/dev/null || echo "0")
                if [[ "$idx_start_epoch" -gt 0 && "$idx_end_epoch" -gt 0 ]]; then
                    index_create_duration_seconds=$((idx_end_epoch - idx_start_epoch))
                fi
                log_info "${db_label} インデックス作成時間: ${index_create_duration_seconds} 秒"
            else
                log_error "Aurora インデックス作成に失敗しましたが、処理を続行します"
            fi
            ;;
        opensearch|s3vectors)
            log_info "${db_label}: インデックス作成はスキップ"
            index_create_success="true"
            ;;
    esac

    # --- Step 6: 投入後レコード数取得 ---
    post_count=$(get_record_count "$target_db")
    log_info "${db_label} 投入後レコード数: ${post_count}"

    # --- Step 7: ログ収集 ---
    collect_task_logs "$target_db" "$RESULT_DIR" || log_error "ログ収集に失敗しましたが、処理を続行します"

    # --- Step 8: メトリクス収集 ---
    local opensearch_ocu_peak_local=0
    case "$target_db" in
        aurora)
            acu_during=$(collect_aurora_metrics)
            if [[ -n "$acu_during" && "$acu_during" != "0" ]]; then
                aurora_acu_peak="$acu_during"
            fi
            ;;
        opensearch)
            opensearch_ocu_peak_local=$(collect_opensearch_metrics)
            if [[ -n "$opensearch_ocu_peak_local" && "$opensearch_ocu_peak_local" != "0" ]]; then
                opensearch_ocu_peak="$opensearch_ocu_peak_local"
            fi
            ;;
        *)
            log_info "${db_label}: メトリクス収集はスキップ"
            ;;
    esac

    # --- Step 9: コスト算出 ---
    local fargate_cost service_cost
    fargate_cost=$(calculate_fargate_cost "$duration_seconds")
    log_info "${db_label} Fargate 概算コスト: \$${fargate_cost}"

    service_cost="0"
    case "$target_db" in
        aurora)
            service_cost=$(calculate_aurora_acu_cost "$acu_during" "$duration_seconds")
            log_info "${db_label} Aurora ACU 概算コスト: \$${service_cost}"
            ;;
        opensearch)
            service_cost=$(calculate_opensearch_ocu_cost "$opensearch_ocu_peak_local" "$duration_seconds")
            log_info "${db_label} OpenSearch OCU 概算コスト: \$${service_cost}"
            ;;
        s3vectors)
            service_cost=$(calculate_s3vectors_cost "$RECORD_COUNT")
            log_info "${db_label} S3 Vectors 概算コスト: \$${service_cost}"
            ;;
    esac

    # --- Step 10: 結果 JSON 保存 ---
    log_info "${db_label} 結果サマリー: 投入前=${pre_count}, 投入後=${post_count}, 処理時間=${duration_seconds}秒, サービスコスト=\$${service_cost}"
    save_result_json "$db_label" "$RECORD_COUNT" "$pre_count" "$post_count" \
        "$START_TIME" "$END_TIME" "$duration_seconds" "$index_drop_success" "$index_create_success" \
        "$TASK_ARN" "$EXIT_CODE" "$acu_before" "$acu_during" "$acu_after" "$cycle_success" "$cycle_error" \
        "$fargate_cost" "$opensearch_ocu_peak_local" "$index_create_duration_seconds" "$service_cost"

    log_info "===== ${db_label} ベンチマークサイクル完了 ====="
}

# =============================================================================
# メイン関数
# =============================================================================

main() {
    # 結果ディレクトリ作成
    create_result_dir

    # 全体開始時刻
    local overall_start
    overall_start=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    log_info "ベンチマーク全体開始: ${overall_start}"

    # グローバル集計変数
    fargate_total_seconds=0
    aurora_acu_peak=0
    opensearch_ocu_peak=0

    # --- Aurora ベンチマーク ---
    log_separator
    log_info "【1/3】Aurora pgvector ベンチマーク開始"
    log_separator
    run_benchmark_cycle "aurora" || true

    # --- 区切りログ ---
    log_separator
    log_info "Aurora ベンチマーク完了。OpenSearch ベンチマークに進みます。"
    log_separator

    # --- OpenSearch ベンチマーク ---
    log_separator
    log_info "【2/3】OpenSearch Serverless ベンチマーク開始"
    log_separator
    run_benchmark_cycle "opensearch" || true

    # --- 区切りログ ---
    log_separator
    log_info "OpenSearch ベンチマーク完了。S3 Vectors ベンチマークに進みます。"
    log_separator

    # --- S3 Vectors ベンチマーク ---
    log_separator
    log_info "【3/3】Amazon S3 Vectors ベンチマーク開始"
    log_separator
    run_benchmark_cycle "s3vectors" || true

    # --- 全体終了 ---
    local overall_end
    overall_end=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    log_info "ベンチマーク全体終了: ${overall_end}"

    # 全体処理時間算出
    local overall_start_epoch overall_end_epoch total_duration_seconds
    overall_start_epoch=$(date -d "$overall_start" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$overall_start" +%s 2>/dev/null || echo "0")
    overall_end_epoch=$(date -d "$overall_end" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$overall_end" +%s 2>/dev/null || echo "0")
    if [[ "$overall_start_epoch" -gt 0 && "$overall_end_epoch" -gt 0 ]]; then
        total_duration_seconds=$((overall_end_epoch - overall_start_epoch))
    else
        total_duration_seconds=0
    fi
    log_info "全体処理時間: ${total_duration_seconds} 秒"

    # Fargate 概算コスト算出
    local fargate_estimated_cost_usd
    fargate_estimated_cost_usd=$(calculate_fargate_cost "$fargate_total_seconds")
    log_info "Fargate 合計実行時間: ${fargate_total_seconds} 秒, 概算コスト: \$${fargate_estimated_cost_usd}"

    # DB サービス概算コスト算出
    local aurora_service_cost_usd=0
    local opensearch_service_cost_usd=0
    local s3vectors_service_cost_usd=0

    if [[ -f "${RESULT_DIR}/aurora-result.json" ]]; then
        aurora_service_cost_usd=$(jq -r '.service_cost_usd // 0' "${RESULT_DIR}/aurora-result.json")
    fi
    if [[ -f "${RESULT_DIR}/opensearch-result.json" ]]; then
        opensearch_service_cost_usd=$(jq -r '.service_cost_usd // 0' "${RESULT_DIR}/opensearch-result.json")
    fi
    if [[ -f "${RESULT_DIR}/s3vectors-result.json" ]]; then
        s3vectors_service_cost_usd=$(jq -r '.service_cost_usd // 0' "${RESULT_DIR}/s3vectors-result.json")
    fi

    # サマリー生成
    generate_summary "$total_duration_seconds" "$fargate_total_seconds" \
        "$fargate_estimated_cost_usd" "$aurora_acu_peak" "$opensearch_ocu_peak" \
        "$aurora_service_cost_usd" "$opensearch_service_cost_usd" "$s3vectors_service_cost_usd"

    # サマリー表示
    print_summary

    log_info "ベンチマーク全体が完了しました。結果: ${RESULT_DIR}/"
}

# =============================================================================
# エントリポイント
# =============================================================================
parse_args "$@"
check_prerequisites
main
