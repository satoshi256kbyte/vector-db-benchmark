# 実装計画

- [x] 1. バグ条件探索テストを作成する
  - **Property 1: Bug Condition** - ECS Waiter タイムアウトと S3 Vectors バッチサイズ過小
  - **重要**: 修正実装の前にこのプロパティベーステストを作成すること
  - **目的**: バグの存在を証明するカウンターサンプルを発見する
  - **スコープ付き PBT アプローチ**: 以下の具体的な失敗ケースにスコープを絞る
  - BATS テスト（`tests/scripts/test_benchmark.bats` に追加）:
    - `run_ecs_task()` 内の `aws ecs wait tasks-stopped` がデフォルト設定（カスタムポーリングループなし）であることを確認
    - `run_ecs_task_with_mode()` 内の `aws ecs wait tasks-stopped` がデフォルト設定であることを確認
    - 未修正コードでは `aws ecs wait tasks-stopped` が使用されており、MAX_WAIT_SECONDS / POLL_INTERVAL 変数が存在しないことを検証
  - pytest テスト（`ecs/bulk-ingest/tests/test_bug_condition_waiter.py` に作成）:
    - `S3VectorsIngester.ingest_all()` のデフォルト batch_size が 50 であることを確認
    - Hypothesis: ランダムな record_count（100000以上）で batch_size=50 の場合、API コール回数が ceil(record_count / 50) = 2000回以上になることを検証
    - `isBugCondition_BatchSize`: batch_size == 50 AND record_count >= 100000 → API コール回数が過大
  - 未修正コードで実行 → テスト失敗を期待（バグの存在を証明）
  - カウンターサンプルを記録: 「S3VectorsIngester.ingest_all(100000) は batch_size=50 で 2000 回の API コールが必要」
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. 保全プロパティテストを作成する（修正実装の前に）
  - **Property 2: Preservation** - 既存 DB バッチサイズと ECS タスク失敗検出の維持
  - **重要**: 観察ファースト手法に従うこと
  - **観察ファースト手法**:
    1. 未修正コードで非バグ入力（isBugCondition が false のケース）を実行
    2. 実際の出力を観察・記録
    3. 観察した動作を捕捉するプロパティベーステストを記述
    4. 未修正コードでテストが成功することを確認
  - pytest テスト（`ecs/bulk-ingest/tests/test_preservation_waiter.py` に作成）:
    - 観察: `AuroraIngester.ingest_all()` のデフォルト batch_size=500 → 未修正コードで確認
    - 観察: `OpenSearchIngester.ingest_all()` のデフォルト batch_size=1000 → 未修正コードで確認
    - 観察: `S3VectorsIngester.ingest_all()` の batch_size 上限チェック（500件）→ 未修正コードで確認
    - 観察: `S3VectorsIngester.ingest_batch()` の PutVectors API 呼び出しフォーマット → 未修正コードで確認
    - Hypothesis: ランダムな record_count で Aurora の batch_size=500、OpenSearch の batch_size=1000 が不変であることを検証
    - Hypothesis: ランダムな batch_size（501以上）で S3VectorsIngester の上限チェックが 500 にクランプすることを検証
  - BATS テスト（`tests/scripts/test_benchmark.bats` に追加）:
    - 観察: `run_ecs_task()` の ECS タスク起動パラメータ（コンテナオーバーライド、ネットワーク設定）→ 未修正コードで確認
    - 観察: `run_ecs_task()` / `run_ecs_task_with_mode()` の戻り値（成功時 0、失敗時 1）→ 未修正コードで確認
  - 未修正コードで実行 → テスト成功を期待（ベースライン動作を確認）
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. ECS Waiter タイムアウトと S3 Vectors バッチサイズの修正

  - [x] 3.1 `scripts/benchmark.sh` の `run_ecs_task()` を修正する
    - `aws ecs wait tasks-stopped` をカスタムポーリングループに置き換える
    - `MAX_WAIT_SECONDS=3600`（最大60分待機）
    - `POLL_INTERVAL=30`（30秒間隔でポーリング）
    - `aws ecs describe-tasks` で `lastStatus` を確認し、`STOPPED` になるまでループ
    - タイムアウト超過時はエラーメッセージを出力して return 1
    - ポーリングごとに経過時間とタスクステータスをログ出力
    - _Bug_Condition: isBugCondition_Waiter(input) where estimated_duration > 600_
    - _Expected_Behavior: カスタムポーリングループが最大3600秒まで待機し、タスク完了を正しく検出_
    - _Preservation: ECS タスク起動パラメータ、戻り値（成功時 0、失敗時 1）は変更しない_
    - _Requirements: 2.1, 3.1, 3.2, 3.8_

  - [x] 3.2 `scripts/benchmark.sh` の `run_ecs_task_with_mode()` を修正する
    - `aws ecs wait tasks-stopped` を同様のカスタムポーリングループに置き換える
    - `run_ecs_task()` と同じ MAX_WAIT_SECONDS=3600、POLL_INTERVAL=30 を使用
    - タイムアウト超過時はエラーメッセージを出力して return 1
    - _Bug_Condition: isBugCondition_Waiter(input) where estimated_duration > 600_
    - _Expected_Behavior: カスタムポーリングループが最大3600秒まで待機し、タスク完了を正しく検出_
    - _Preservation: ECS タスク起動パラメータ、戻り値（成功時 0、失敗時 1）は変更しない_
    - _Requirements: 2.2, 3.3, 3.4, 3.8_

  - [x] 3.3 `ecs/bulk-ingest/ingestion.py` の `S3VectorsIngester.ingest_all()` を修正する
    - デフォルト `batch_size` を 50 から 200 に変更
    - docstring を更新: バッチサイズ変更の理由を反映
    - batch_size 上限チェック（500件）は維持する
    - _Bug_Condition: isBugCondition_BatchSize(input) where batch_size == 50 AND record_count >= 100000_
    - _Expected_Behavior: batch_size=200 で API コール回数が 1/4 に削減_
    - _Preservation: AuroraIngester.ingest_all() の batch_size=500、OpenSearchIngester.ingest_all() の batch_size=1000 は変更しない_
    - _Requirements: 2.3, 3.5, 3.6, 3.7_

  - [x] 3.4 バグ条件探索テストが成功することを確認する
    - **Property 1: Expected Behavior** - ECS Waiter タイムアウトと S3 Vectors バッチサイズ修正
    - **重要**: タスク 1 と同じテストを再実行する（新しいテストは書かない）
    - タスク 1 のテストは期待される動作をエンコードしている
    - テスト成功 → バグが修正されたことを確認
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.5 保全プロパティテストが引き続き成功することを確認する
    - **Property 2: Preservation** - 既存 DB バッチサイズと ECS タスク失敗検出の維持
    - **重要**: タスク 2 と同じテストを再実行する（新しいテストは書かない）
    - テスト成功 → リグレッションがないことを確認
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 4. チェックポイント - 全テストが成功することを確認する
  - 全テストを実行して成功を確認する（pytest + BATS）
  - 質問がある場合はユーザーに確認する
