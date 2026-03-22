# 実装計画

- [x] 1. バグ条件探索テストの作成
  - **Property 1: Bug Condition** - Aurora テーブル未存在時の SQL 実行エラー
  - **重要**: このプロパティベーステストは修正実装の前に作成すること
  - **目的**: バグの存在を確認する反例を表面化させる
  - **スコープ付き PBT アプローチ**: `embeddings` テーブルが存在しない状態で `drop_index()` および `ingest_batch()` を呼び出す具体的なケースにスコープを限定
  - テスト内容（設計ドキュメントのバグ条件より）:
    - `isBugCondition_Aurora`: `target_db == "aurora"` かつ `task_mode IN ["index_drop", "ingest"]` かつ `NOT tableExists("embeddings")`
    - テーブル未存在時に `AuroraIndexManager.drop_index()` を呼び出し、`TRUNCATE TABLE embeddings` が例外を発生させることを確認
    - テーブル未存在時に `AuroraIngester.ingest_batch()` を呼び出し、`INSERT INTO embeddings` が例外を発生させることを確認
    - pgvector 拡張未インストール時に `vector` 型が認識されないことを確認
  - テストアサーションは設計ドキュメントの期待される動作プロパティに一致させる:
    - 修正後: `ensure_table()` により pgvector 拡張の有効化とテーブル自動作成が行われ、後続の SQL 操作が正常完了する
  - 未修正コードでテストを実行する
  - **期待される結果**: テストが失敗する（これはバグの存在を証明する正しい結果）
  - 発見された反例を文書化し、根本原因を理解する
  - テストの作成・実行・失敗の文書化が完了したらタスクを完了とする
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. 保全プロパティテストの作成（修正実装の前に）
  - **Property 2: Preservation** - 既存 Aurora 動作と他 DB 動作の維持
  - **重要**: 観察ファーストの方法論に従うこと
  - 観察: 未修正コードで以下の動作を確認する
    - `embeddings` テーブルが既に存在する場合、`drop_index()` は HNSW インデックス削除と TRUNCATE を正常実行する
    - `embeddings` テーブルが既に存在する場合、`ingest_batch()` は INSERT を正常実行する
    - `_run_count_operation()` のテーブル未存在ハンドリング（`does not exist` → count=0）は正常動作する
    - `AuroraIndexManager.create_index()` は HNSW インデックスを正常作成する
  - プロパティベーステスト作成（設計ドキュメントの保全要件より）:
    - テーブル存在時の `drop_index()` が従来通り TRUNCATE を正常実行することを検証
    - テーブル存在時の `ingest_batch()` が従来通り INSERT を正常実行することを検証（ランダムなバッチデータを生成）
    - `create_index()` が HNSW インデックスを正常作成することを検証
    - `_run_count_operation()` の既存エラーハンドリングが変更されていないことを検証
  - 未修正コードでテストを実行する
  - **期待される結果**: テストが成功する（保全すべきベースライン動作を確認）
  - テストの作成・実行・成功の確認が完了したらタスクを完了とする
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 3. バグ修正の実装

  - [x] 3.1 `AuroraIndexManager` に `ensure_table()` メソッドを追加し、`drop_index()` を修正する
    - `ecs/bulk-ingest/index_manager.py` を修正
    - `ensure_table()` メソッドを追加: `CREATE EXTENSION IF NOT EXISTS vector` と `CREATE TABLE IF NOT EXISTS embeddings (content TEXT, embedding vector(1536))` を実行
    - `drop_index()` を修正: `TRUNCATE TABLE` 実行前にテーブル存在チェックを追加。テーブルが存在しない場合はスキップ（ログ出力のみ）
    - _Bug_Condition: isBugCondition_Aurora(input) where target_db == "aurora" AND task_mode IN ["index_drop", "ingest"] AND NOT tableExists("embeddings")_
    - _Expected_Behavior: ensure_table() により pgvector 拡張有効化 + テーブル自動作成後、後続 SQL 操作が正常完了_
    - _Preservation: テーブル存在時の TRUNCATE/INSERT 動作は変更なし_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.2 `ingestion.py` と `main.py` で `ensure_table()` を呼び出す
    - `ecs/bulk-ingest/ingestion.py` を修正: `AuroraIngester.ingest_all()` でデータ投入開始前に `ensure_table()` を呼び出す
    - `ecs/bulk-ingest/main.py` を修正: `_run_index_operation()` で Aurora の `index_drop` 実行前に `ensure_table()` を呼び出す
    - `_run_single_database()` と `_run_all_databases()` で Aurora のデータ投入前に `ensure_table()` を呼び出す
    - _Bug_Condition: isBugCondition_Aurora(input) where NOT tableExists("embeddings")_
    - _Expected_Behavior: ensure_table() がデータ投入・インデックス操作の前に呼ばれ、テーブルの存在を保証_
    - _Preservation: 既存の処理フロー（接続→操作→結果出力）は変更なし_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 `network.ts` から `aoss` Interface VPC Endpoint を削除する
    - `lib/constructs/network.ts` を修正: `OpenSearchServerlessEndpoint`（`com.amazonaws.${region}.aoss`）の Interface VPC Endpoint を削除
    - OpenSearch Serverless は `opensearch.ts` の `CfnVpcEndpoint` を使用するため、標準 Interface VPC Endpoint は不要
    - DNS 解決の競合を解消し、ISOLATED サブネットからの OpenSearch Serverless 接続を正常化
    - _Bug_Condition: isBugCondition_OpenSearch(input) where target_db IN ["opensearch", "all"] AND opensearchConnectionFails()_
    - _Expected_Behavior: VPC エンドポイント経由で OpenSearch Serverless コレクションに正常接続_
    - _Preservation: 他の VPC エンドポイント（Secrets Manager, CloudWatch Logs, S3 Vectors, ECR）は変更なし_
    - _Requirements: 2.4_

  - [x] 3.4 バグ条件探索テストが成功することを確認する
    - **Property 1: Expected Behavior** - Aurora テーブル自動作成
    - **重要**: タスク 1 と同じテストを再実行する（新しいテストは書かない）
    - タスク 1 のテストは期待される動作をエンコードしている
    - このテストが成功すれば、期待される動作が満たされたことを確認できる
    - バグ条件探索テスト（タスク 1）を再実行する
    - **期待される結果**: テストが成功する（バグが修正されたことを確認）
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.5 保全テストが引き続き成功することを確認する
    - **Property 2: Preservation** - 既存 Aurora 動作と他 DB 動作の維持
    - **重要**: タスク 2 と同じテストを再実行する（新しいテストは書かない）
    - 保全プロパティテスト（タスク 2）を再実行する
    - **期待される結果**: テストが成功する（リグレッションなしを確認）
    - 修正後もすべてのテストが成功することを確認する

- [x] 4. チェックポイント - 全テスト成功の確認
  - すべてのテスト（探索テスト + 保全テスト + 既存テスト）が成功することを確認する
  - 質問がある場合はユーザーに確認する
