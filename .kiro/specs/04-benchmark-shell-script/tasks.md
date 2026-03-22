# 実装タスク: ベンチマークシェルスクリプト

## 概要

ECS タスク（main.py）に `TARGET_DB` / `TASK_MODE` 環境変数対応を追加し、ローカル PC から実行するベンチマークシェルスクリプト（`scripts/benchmark.sh`）を作成する。スクリプトは Aurora → OpenSearch → S3 Vectors の順に、ACU/OCU スケーリング・インデックス操作・データ投入・メトリクス収集を自動実行する。

## タスク

- [x] 1. ECS タスク main.py の TARGET_DB / TASK_MODE 環境変数対応
  - [x] 1.1 `ecs/bulk-ingest/main.py` に `TARGET_DB` 環境変数によるルーティングロジックを実装する
    - `TARGET_DB` の値（`all`, `aurora`, `opensearch`, `s3vectors`）に応じて処理対象 DB を切り替える
    - 無効な `TARGET_DB` 値の場合はエラーログ出力 + `sys.exit(1)` で終了する
    - `TARGET_DB=all`（または未設定）の場合は既存動作を維持する（後方互換性）
    - 単一 DB 指定時はインデックス操作をスキップし、データ投入のみ実行する
    - _要件: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 1.2 `ecs/bulk-ingest/main.py` に `TASK_MODE` 環境変数によるインデックス操作モードを実装する
    - `TASK_MODE=index_drop`: 指定 DB のインデックス削除のみ実行
    - `TASK_MODE=index_create`: 指定 DB のインデックス作成のみ実行
    - `TASK_MODE=ingest`（デフォルト）: データ投入モード
    - 無効な `TASK_MODE` 値の場合はエラーログ出力 + `sys.exit(1)` で終了する
    - _要件: 4.3, 4.4_
  - [x] 1.3 `tests/ecs/bulk_ingest/test_main_routing.py` にプロパティテストを作成する
    - **プロパティ 1: TARGET_DB ルーティングの正確性**
    - **検証対象: 要件 1.1, 1.2, 1.3, 1.6**
  - [x] 1.4 `tests/ecs/bulk_ingest/test_main_routing.py` にプロパティテストを作成する
    - **プロパティ 2: 無効な TARGET_DB の拒否**
    - **検証対象: 要件 1.5**
  - [x] 1.5 `tests/ecs/bulk_ingest/test_main_routing.py` にプロパティテストを作成する
    - **プロパティ 7: TASK_MODE ルーティングの正確性**
    - **検証対象: 要件 4.3, 4.4**
  - [x] 1.6 `tests/ecs/bulk_ingest/test_main_integration.py` にユニットテストを作成する
    - `TARGET_DB=all` の後方互換性テスト（3DB 順次処理、インデックス操作含む）
    - `index_drop` / `index_create` モードの動作テスト（mock 使用）
    - _要件: 1.4, 4.3, 4.4_

- [x] 2. チェックポイント - ECS タスク修正の確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

- [x] 3. シェルスクリプトの基盤実装（引数パース・前提条件チェック・ユーティリティ）
  - [x] 3.1 `scripts/benchmark.sh` を作成し、基本構造を実装する
    - shebang (`#!/usr/bin/env bash`)、`set -euo pipefail`
    - デフォルト値定義（`RECORD_COUNT=100000`, `AURORA_CLUSTER=vdbbench-dev-aurora-pgvector`, `REGION=ap-northeast-1` 等）
    - `parse_args` 関数: `--record-count`, `--aurora-cluster`, `--opensearch-collection`, `--s3vectors-bucket`, `--ecs-cluster`, `--region`, `--aurora-min-acu`, `--opensearch-max-ocu`, `--help` の引数パース
    - `check_prerequisites` 関数: `aws`, `psql`, `jq` コマンドの存在確認、`aws sts get-caller-identity` による認証情報確認
    - `log_info`, `log_error`, `log_separator` ログユーティリティ関数
    - _要件: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.1, 11.5_

- [x] 4. シェルスクリプトの ACU/OCU スケーリングとクリーンアップ実装
  - [x] 4.1 `scripts/benchmark.sh` に Aurora ACU スケーリング関数を追加する
    - `scale_aurora_up`: `aws rds modify-db-cluster` で最小 ACU を拡張
    - `scale_aurora_down`: 最小 ACU を元の値（0）に復元
    - `wait_aurora_available`: クラスターステータスが `available` になるまでポーリング（30秒間隔、最大20分）
    - ACU 変更前後の設定値をログ記録
    - _要件: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 4.2 `scripts/benchmark.sh` に OpenSearch OCU スケーリング関数を追加する
    - `scale_opensearch_up`: `aws opensearchserverless update-account-settings` で OCU 上限を拡張
    - `scale_opensearch_down`: OCU 上限を元の値（2）に復元
    - OCU 変更前後の設定値をログ記録
    - _要件: 3.1, 3.2, 3.3, 3.4_
  - [x] 4.3 `scripts/benchmark.sh` に `cleanup` 関数と `trap cleanup EXIT` を実装する
    - `AURORA_SCALED_UP` / `OPENSEARCH_SCALED_UP` フラグで復元要否を判定
    - クリーンアップ内の AWS CLI 呼び出しは `2>/dev/null || true` でエラーを無視
    - _要件: 11.2, 11.3, 11.4_

- [x] 5. シェルスクリプトのインデックス操作と ECS タスク実行
  - [x] 5.1 `scripts/benchmark.sh` に Aurora インデックス操作関数を追加する
    - `get_aurora_credentials`: Secrets Manager から認証情報取得
    - `drop_aurora_index`: psql で `DROP INDEX IF EXISTS embeddings_hnsw_idx` + `TRUNCATE TABLE embeddings`
    - `create_aurora_index`: psql で HNSW インデックス再作成
    - _要件: 4.1, 4.2, 4.6, 4.7_
  - [x] 5.2 `scripts/benchmark.sh` に OpenSearch インデックス操作関数を追加する
    - `drop_opensearch_index`: ECS タスクを `TASK_MODE=index_drop` で起動・待機
    - `create_opensearch_index`: ECS タスクを `TASK_MODE=index_create` で起動・待機
    - `run_ecs_task_with_mode`: 指定 TARGET_DB + TASK_MODE で ECS タスクを起動し完了待機する汎用関数
    - _要件: 4.3, 4.4, 4.5, 4.6, 4.7_
  - [x] 5.3 `scripts/benchmark.sh` に ECS タスク実行関数を追加する
    - `run_ecs_task`: `aws ecs run-task` で TARGET_DB + RECORD_COUNT を指定して起動
    - `aws ecs wait tasks-stopped` で完了待機
    - 開始時刻・終了時刻（ISO 8601）の記録
    - 終了コード確認（`aws ecs describe-tasks`）
    - _要件: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 6. シェルスクリプトのメトリクス収集と結果出力
  - [x] 6.1 `scripts/benchmark.sh` にレコード数取得関数を追加する
    - `get_aurora_record_count`: psql 経由で `SELECT COUNT(*) FROM embeddings`
    - `get_opensearch_record_count`: ECS タスクログから取得（VPC 制限のため）
    - `get_s3vectors_record_count`: `aws s3vectors list-vectors` で取得
    - _要件: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 6.2 `scripts/benchmark.sh` にログ収集・メトリクス取得関数を追加する
    - `collect_task_logs`: CloudWatch Logs からタスク ID でフィルタしてログ取得、ファイル保存
    - `collect_aurora_metrics`: CloudWatch メトリクス（ServerlessDatabaseCapacity）から ACU 値取得
    - `calculate_fargate_cost`: Fargate 概算コスト算出（vCPU: $0.05056/h, メモリ: $0.00553/GB/h）
    - _要件: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4_
  - [x] 6.3 `scripts/benchmark.sh` に結果 JSON 生成関数を追加する
    - `save_result_json`: 個別 DB 結果 JSON（aurora-result.json 等）を生成・保存
    - `generate_summary`: 全 DB 統合サマリー JSON（summary.json）を生成
    - 結果ディレクトリ `results/YYYYMMDD-HHMMSS/` の作成
    - 実行完了時にサマリーをコンソール表示
    - _要件: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 7. シェルスクリプトのメインフロー統合
  - [x] 7.1 `scripts/benchmark.sh` に `run_benchmark_cycle` 関数と `main` 関数を実装する
    - `run_benchmark_cycle`: 1つの DB に対するベンチマークサイクル全体（スケーリング→インデックス削除→ECS タスク→インデックス作成→メトリクス収集→スケーリング復元）
    - `main`: Aurora → OpenSearch → S3 Vectors の順に `run_benchmark_cycle` を呼び出し、サマリー生成
    - 各 DB 処理間に区切りログ出力
    - 1つの DB でエラーが発生しても次の DB の処理に進む
    - _要件: 12.1, 12.2, 12.3, 12.4, 11.3_

- [x] 8. チェックポイント - シェルスクリプト実装の確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

- [x] 9. Python テスト（コスト算出・処理時間・結果 JSON）
  - [x] 9.1 `tests/scripts/test_duration_calc.py` にプロパティテストを作成する
    - **プロパティ 3: 処理時間算出の正確性**
    - **検証対象: 要件 5.6**
  - [x] 9.2 `tests/scripts/test_cost_calculation.py` にプロパティテストを作成する
    - **プロパティ 4: Fargate 概算コスト算出の正確性**
    - **検証対象: 要件 8.3**
  - [x] 9.3 `tests/scripts/test_result_json.py` にプロパティテストを作成する
    - **プロパティ 5: 結果 JSON の必須フィールド完全性**
    - **検証対象: 要件 9.2, 9.4**

- [x] 10. シェルスクリプトテスト（bats-core）
  - [x] 10.1 `tests/scripts/test_benchmark.bats` にコマンドライン引数パーステストを作成する
    - **プロパティ 6: コマンドライン引数パースとデフォルト値**
    - **検証対象: 要件 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8**
  - [x] 10.2 `tests/scripts/test_benchmark.bats` に前提条件チェック・ヘルプ表示・エラー継続のユニットテストを作成する
    - 前提条件チェック（aws, psql, jq 不在時のエラー）
    - `--help` オプションの出力確認
    - DB 処理順序（Aurora → OpenSearch → S3 Vectors）の検証
    - エラー発生時の次 DB 継続動作の検証
    - _要件: 10.9, 11.3, 11.5, 12.1_

- [x] 11. 最終チェックポイント - 全テスト pass を確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

## 備考

- `*` 付きタスクはオプションであり、スキップ可能
- 各タスクは対応する要件番号を参照しトレーサビリティを確保
- プロパティテストは設計書の正当性プロパティ番号に対応
- チェックポイントで段階的に動作確認を実施
