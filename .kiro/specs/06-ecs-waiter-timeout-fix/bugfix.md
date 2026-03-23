# バグ修正要件ドキュメント

## はじめに

ベンチマークスクリプト (`scripts/benchmark.sh`) で S3 Vectors に 100,000 件のデータを投入する ECS タスクが、`aws ecs wait tasks-stopped` のデフォルトタイムアウト（約10分）を超過して失敗する。

根本原因は2つある:

1. **シェルスクリプト側**: `aws ecs wait tasks-stopped` のデフォルト設定（100回ポーリング × 6秒間隔 ≈ 10分）では、大量データ投入タスクの完了を待機しきれない
2. **Python 側**: `S3VectorsIngester.ingest_all()` のデフォルトバッチサイズが 50 件と小さく、100,000 件投入に 2,000 回の PutVectors API コールが必要となり、処理時間が 10 分を大幅に超過する

Aurora（batch_size=500）や OpenSearch（batch_size=1000）は API コール回数が少ないため 10 分以内に完了するが、S3 Vectors のみタイムアウトする。

## バグ分析

### 現在の動作（不具合）

1.1 WHEN `run_ecs_task()` で S3 Vectors に 100,000 件のデータ投入タスクを起動し、タスクの完了に 10 分以上かかる場合 THEN `aws ecs wait tasks-stopped` がデフォルトタイムアウト（100回 × 6秒 ≈ 10分）で `Waiter TasksStopped failed: Max attempts exceeded` エラーを返し、ベンチマークサイクルが失敗する

1.2 WHEN `run_ecs_task_with_mode()` で長時間かかる ECS タスクを起動し、タスクの完了に 10 分以上かかる場合 THEN `aws ecs wait tasks-stopped` が同様にデフォルトタイムアウトで失敗する

1.3 WHEN `S3VectorsIngester.ingest_all()` が batch_size=50 で 100,000 件を投入する場合 THEN 2,000 回の PutVectors API コールが必要となり、ネットワークレイテンシの累積により処理時間が 10 分を大幅に超過する

### 期待される動作（正常）

2.1 WHEN `run_ecs_task()` で S3 Vectors に 100,000 件のデータ投入タスクを起動し、タスクの完了に 10 分以上かかる場合 THEN スクリプトは十分な待機時間（最大60分程度）を確保してタスク完了を待機し、タスクが正常終了すればベンチマークサイクルが成功する

2.2 WHEN `run_ecs_task_with_mode()` で長時間かかる ECS タスクを起動し、タスクの完了に 10 分以上かかる場合 THEN スクリプトは十分な待機時間を確保してタスク完了を待機し、タスクが正常終了すればベンチマークサイクルが成功する

2.3 WHEN `S3VectorsIngester.ingest_all()` が 100,000 件を投入する場合 THEN バッチサイズを増加させて API コール回数を削減し、処理時間を短縮する（PutVectors API の上限 500 件/回およびペイロード 20MiB 制限の範囲内で）

### 変更されない動作（リグレッション防止）

3.1 WHEN `run_ecs_task()` で Aurora に 100,000 件のデータ投入タスクを起動する場合 THEN 従来通り ECS タスクが正常に完了し、ベンチマークサイクルが成功する

3.2 WHEN `run_ecs_task()` で OpenSearch に 100,000 件のデータ投入タスクを起動する場合 THEN 従来通り ECS タスクが正常に完了し、ベンチマークサイクルが成功する

3.3 WHEN `run_ecs_task_with_mode()` で `count` モードの ECS タスクを起動する場合 THEN 従来通り短時間で完了し、レコード数が正しく取得される

3.4 WHEN `run_ecs_task_with_mode()` で `index_drop` または `index_create` モードの ECS タスクを起動する場合 THEN 従来通りインデックス操作が正常に完了する

3.5 WHEN `S3VectorsIngester.ingest_batch()` が PutVectors API を呼び出す場合 THEN 従来通り正しいフォーマットでベクトルデータが投入される

3.6 WHEN `AuroraIngester.ingest_all()` が batch_size=500 でデータ投入する場合 THEN バッチサイズは変更されず、従来通り動作する

3.7 WHEN `OpenSearchIngester.ingest_all()` が batch_size=1000 でデータ投入する場合 THEN バッチサイズは変更されず、従来通り動作する

3.8 WHEN ECS タスクが実際にエラーで失敗した場合 THEN 待機時間の延長に関わらず、タスク失敗が正しく検出されエラーが報告される
