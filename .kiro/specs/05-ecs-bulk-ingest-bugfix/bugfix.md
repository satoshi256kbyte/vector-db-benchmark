# バグ修正要件ドキュメント

## はじめに

ベンチマークスクリプト (`scripts/benchmark.sh`) を実行して ECS タスク経由でデータ投入と計測を行った際、2つの異なるエラーにより ECS タスクが失敗する。

1. **Aurora `index_drop` でテーブル未存在エラー**: 初回実行時に `embeddings` テーブルが存在しないため、`TRUNCATE TABLE embeddings;` が `relation "embeddings" does not exist` エラーで失敗する。また、`ingest` モードでも `INSERT INTO embeddings` がテーブル未存在で失敗する。
2. **OpenSearch Serverless への接続失敗**: ECS タスクから OpenSearch Serverless コレクションへの接続が `OpenSearch connection failed after 3 retries` で失敗する。ISOLATED サブネットからの VPC エンドポイント経由の接続に問題がある可能性。

これらのバグにより、ベンチマーク全体が実行不能となっている。

## バグ分析

### 現在の動作（不具合）

1.1 WHEN `TASK_MODE=index_drop` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが存在しない場合 THEN `AuroraIndexManager.drop_index()` が `TRUNCATE TABLE embeddings;` を実行し、`relation "embeddings" does not exist` エラーで ECS タスクが異常終了する

1.2 WHEN `TASK_MODE=ingest` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが存在しない場合 THEN `AuroraIngester.ingest_batch()` が `INSERT INTO embeddings` を実行し、テーブル未存在エラーで ECS タスクが異常終了する

1.3 WHEN `TASK_MODE=ingest` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に pgvector 拡張がインストールされていない場合 THEN `vector` 型が認識されず、テーブル作成やデータ投入が失敗する

1.4 WHEN `TASK_MODE=ingest` または `TASK_MODE=index_drop` かつ `TARGET_DB=opensearch` で ECS タスクを実行する場合 THEN `_get_opensearch_client()` が OpenSearch Serverless コレクションへの接続に失敗し、`OpenSearch connection failed after 3 retries` エラーで ECS タスクが異常終了する

### 期待される動作（正常）

2.1 WHEN `TASK_MODE=index_drop` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが存在しない場合 THEN `AuroraIndexManager.drop_index()` はテーブル未存在を検知して正常に完了し（エラーなし）、ECS タスクが正常終了する（終了コード 0）

2.2 WHEN `TASK_MODE=ingest` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが存在しない場合 THEN pgvector 拡張の有効化とテーブルの自動作成が行われた後、`INSERT INTO embeddings` が正常に実行され、データ投入が成功する

2.3 WHEN `TASK_MODE=ingest` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に pgvector 拡張がインストールされていない場合 THEN `CREATE EXTENSION IF NOT EXISTS vector;` が自動実行され、その後のテーブル作成とデータ投入が正常に完了する

2.4 WHEN `TASK_MODE=ingest` または `TASK_MODE=index_drop` かつ `TARGET_DB=opensearch` で ECS タスクを実行する場合 THEN ECS タスクが VPC エンドポイント経由で OpenSearch Serverless コレクションに正常に接続でき、操作が成功する

### 変更されない動作（リグレッション防止）

3.1 WHEN `TASK_MODE=index_drop` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが既に存在する場合 THEN `AuroraIndexManager.drop_index()` は従来通り HNSW インデックスの削除とテーブルの TRUNCATE を正常に実行する

3.2 WHEN `TASK_MODE=ingest` かつ `TARGET_DB=aurora` で ECS タスクを実行し、Aurora に `embeddings` テーブルが既に存在する場合 THEN `AuroraIngester.ingest_batch()` は従来通り `INSERT INTO embeddings` でデータ投入を正常に実行する

3.3 WHEN `TASK_MODE=count` かつ `TARGET_DB=aurora` で ECS タスクを実行する場合 THEN `_run_count_operation()` の既存のテーブル未存在ハンドリング（`does not exist` → count=0）は変更されず、従来通り動作する

3.4 WHEN `TASK_MODE=index_create` かつ `TARGET_DB=aurora` で ECS タスクを実行する場合 THEN `AuroraIndexManager.create_index()` は従来通り HNSW インデックスを正常に作成する

3.5 WHEN `TARGET_DB=s3vectors` で ECS タスクを実行する場合 THEN S3 Vectors への接続とデータ投入は従来通り正常に動作する

3.6 WHEN `TARGET_DB=opensearch` かつ `TASK_MODE=count` で ECS タスクを実行する場合 THEN `_run_count_operation()` の既存のインデックス未存在ハンドリング（`index_not_found_exception` → count=0）は変更されず、従来通り動作する

3.7 WHEN `TARGET_DB=all` で ECS タスクを実行する場合 THEN `_run_all_databases()` の既存の全 DB 順次処理フローは変更されず、従来通り動作する
