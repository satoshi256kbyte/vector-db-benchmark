# 実装タスク: ベンチマークシェルスクリプト

## 概要

ECS タスク（main.py）に `TARGET_DB` 環境変数対応を追加し、ローカル PC から実行するベンチマークシェルスクリプト（`scripts/benchmark.sh`）を作成する。スクリプトは Aurora → OpenSearch → S3 Vectors の順に、インデックス操作（Aurora のみ）・データ投入・メトリクス収集を自動実行する。ACU/OCU は CDK 側で固定設定済みのため、シェルスクリプトからのスケーリング操作は行わない。

## タスク

- [x] 1. ECS タスク main.py の TARGET_DB 環境変数対応
  - [x] 1.1 `ecs/bulk-ingest/main.py` に `TARGET_DB` 環境変数によるルーティングロジックを実装する
    - `TARGET_DB` の値（`all`, `aurora`, `opensearch`, `s3vectors`）に応じて処理対象 DB を切り替える
    - 無効な `TARGET_DB` 値の場合はエラーログ出力 + `sys.exit(1)` で終了する
    - `TARGET_DB=all`（または未設定）の場合は既存動作を維持する（後方互換性）
    - 単一 DB 指定時はインデックス操作をスキップし、データ投入のみ実行する
    - _要件: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 1.2 `tests/ecs/bulk_ingest/test_main_routing.py` にプロパティテストを作成する
    - **プロパティ 1: TARGET_DB ルーティングの正確性**
    - **検証対象: 要件 1.1, 1.2, 1.3, 1.6**
  - [x] 1.3 `tests/ecs/bulk_ingest/test_main_routing.py` にプロパティテストを作成する
    - **プロパティ 2: 無効な TARGET_DB の拒否**
    - **検証対象: 要件 1.5**
  - [x] 1.4 `tests/ecs/bulk_ingest/test_main_integration.py` にユニットテストを作成する
    - `TARGET_DB=all` の後方互換性テスト（3DB 順次処理、インデックス操作含む）
    - _要件: 1.4_

- [x] 2. チェックポイント - ECS タスク修正の確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

- [x] 3. シェルスクリプトの基盤実装（引数パース・前提条件チェック・ユーティリティ）
  - [x] 3.1 `scripts/benchmark.sh` を作成し、基本構造を実装する
    - shebang (`#!/usr/bin/env bash`)、`set -euo pipefail`
    - デフォルト値定義（`RECORD_COUNT=100000`, `AURORA_CLUSTER=vdbbench-dev-aurora-pgvector`, `REGION=ap-northeast-1` 等）
    - `parse_args` 関数: `--record-count`, `--aurora-cluster`, `--opensearch-collection`, `--s3vectors-bucket`, `--ecs-cluster`, `--region`, `--help` の引数パース
    - `check_prerequisites` 関数: `aws`, `psql`, `jq` コマンドの存在確認、`aws sts get-caller-identity` による認証情報確認
    - `log_info`, `log_error`, `log_separator` ログユーティリティ関数
    - _要件: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.5_

- [x] 4. シェルスクリプトのインデックス操作と ECS タスク実行
  - [x] 4.1 `scripts/benchmark.sh` に Aurora インデックス操作関数を追加する
    - `get_aurora_credentials`: Secrets Manager から認証情報取得
    - `drop_aurora_index`: psql で `DROP INDEX IF EXISTS embeddings_hnsw_idx` + `TRUNCATE TABLE embeddings`
    - `create_aurora_index`: psql で HNSW インデックス再作成
    - _要件: 2.1, 2.2, 2.5, 2.6_
  - [x] 4.2 `scripts/benchmark.sh` に ECS タスク実行関数を追加する
    - `run_ecs_task`: `aws ecs run-task` で TARGET_DB + RECORD_COUNT を指定して起動
    - `aws ecs wait tasks-stopped` で完了待機
    - 開始時刻・終了時刻（ISO 8601）の記録
    - 終了コード確認（`aws ecs describe-tasks`）
    - _要件: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
  - [x] 4.3 `scripts/benchmark.sh` に `cleanup` 関数と `trap cleanup EXIT` を実装する
    - ACU/OCU は CDK 側で固定設定済みのため、スケーリング復元処理は不要
    - 一時ファイルの削除等、必要な後処理を行う
    - _要件: 9.2, 9.3, 9.4_

- [x] 5. シェルスクリプトのメトリクス収集と結果出力
  - [x] 5.1 `scripts/benchmark.sh` にレコード数取得関数を追加する
    - `get_aurora_record_count`: psql 経由で `SELECT COUNT(*) FROM embeddings`
    - `get_opensearch_record_count`: ECS タスクログから取得（VPC 制限のため）
    - `get_s3vectors_record_count`: `aws s3vectors list-vectors` で取得
    - _要件: 4.1, 4.2, 4.3, 4.4, 4.5_
  - [x] 5.2 `scripts/benchmark.sh` にログ収集・メトリクス取得関数を追加する
    - `collect_task_logs`: CloudWatch Logs からタスク ID でフィルタしてログ取得、ファイル保存
    - `collect_aurora_metrics`: CloudWatch メトリクス（ServerlessDatabaseCapacity）から現在の ACU 値取得
    - `calculate_fargate_cost`: Fargate 概算コスト算出（vCPU: $0.05056/h, メモリ: $0.00553/GB/h）
    - _要件: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_
  - [x] 5.3 `scripts/benchmark.sh` に結果 JSON 生成関数を追加する
    - `save_result_json`: 個別 DB 結果 JSON（aurora-result.json 等）を生成・保存
    - `generate_summary`: 全 DB 統合サマリー JSON（summary.json）を生成
    - 結果ディレクトリ `results/YYYYMMDD-HHMMSS/` の作成
    - 実行完了時にサマリーをコンソール表示
    - _要件: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 6. シェルスクリプトのメインフロー統合
  - [x] 6.1 `scripts/benchmark.sh` に `run_benchmark_cycle` 関数と `main` 関数を実装する
    - `run_benchmark_cycle`: 1つの DB に対するベンチマークサイクル全体
      - Aurora: 投入前レコード数記録 → インデックス削除（psql）→ ECS タスク起動 → ECS タスク完了待機 → インデックス作成（psql）→ 投入後レコード数記録 → ログ収集 → メトリクス記録
      - OpenSearch: 投入前レコード数記録 → ECS タスク起動（Bulk API）→ ECS タスク完了待機 → 投入後レコード数記録 → ログ収集 → メトリクス記録
      - S3 Vectors: 投入前レコード数記録 → ECS タスク起動 → ECS タスク完了待機 → 投入後レコード数記録 → ログ収集 → メトリクス記録
    - `main`: Aurora → OpenSearch → S3 Vectors の順に `run_benchmark_cycle` を呼び出し、サマリー生成
    - 各 DB 処理間に区切りログ出力
    - 1つの DB でエラーが発生しても次の DB の処理に進む
    - _要件: 10.1, 10.2, 10.3, 10.4, 9.3_

- [x] 7. チェックポイント - シェルスクリプト実装の確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

- [x] 8. Python テスト（コスト算出・処理時間・結果 JSON）
  - [x] 8.1 `tests/scripts/test_duration_calc.py` にプロパティテストを作成する
    - **プロパティ 3: 処理時間算出の正確性**
    - **検証対象: 要件 3.6**
  - [x] 8.2 `tests/scripts/test_cost_calculation.py` にプロパティテストを作成する
    - **プロパティ 4: Fargate 概算コスト算出の正確性**
    - **検証対象: 要件 6.3**
  - [x] 8.3 `tests/scripts/test_result_json.py` にプロパティテストを作成する
    - **プロパティ 5: 結果 JSON の必須フィールド完全性**
    - **検証対象: 要件 7.2, 7.4**

- [x] 9. シェルスクリプトテスト（bats-core）
  - [x] 9.1 `tests/scripts/test_benchmark.bats` にコマンドライン引数パーステストを作成する
    - **プロパティ 6: コマンドライン引数パースとデフォルト値**
    - **検証対象: 要件 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**
  - [x] 9.2 `tests/scripts/test_benchmark.bats` に前提条件チェック・ヘルプ表示・エラー継続のユニットテストを作成する
    - 前提条件チェック（aws, psql, jq 不在時のエラー）
    - `--help` オプションの出力確認
    - DB 処理順序（Aurora → OpenSearch → S3 Vectors）の検証
    - エラー発生時の次 DB 継続動作の検証
    - _要件: 8.7, 9.3, 9.5, 10.1_

- [x] 10. 最終チェックポイント - 全テスト pass を確認
  - 全テスト pass を確認し、不明点があればユーザーに質問する

## 備考

- `*` 付きタスクはオプションであり、スキップ可能
- 各タスクは対応する要件番号を参照しトレーサビリティを確保
- プロパティテストは設計書の正当性プロパティ番号に対応
- チェックポイントで段階的に動作確認を実施
- ACU/OCU は CDK 側で固定設定済み（ACU: 最小0/最大10、OCU: 検索・インデックスともに最大10）のため、シェルスクリプトからのスケーリング操作は不要
- OpenSearch は既存インデックスに Bulk API で一括投入するのみ（インデックス削除・作成は行わない）
