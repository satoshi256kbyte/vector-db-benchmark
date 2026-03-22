# タスク

## 1. VPCネットワーク拡張（ECS Fargate対応）

- [x] 1.1 NetworkConstruct に ECS Fargate 用セキュリティグループ（`vdbbench-dev-sg-ecs`）を追加し、VPC EP SG:443 と Aurora SG:5432 へのアウトバウンドルールを設定する
- [x] 1.2 既存の Aurora SG に ECS SG からのインバウンド（5432）、既存の VPC EP SG に ECS SG からのインバウンド（443）を追加する
- [x] 1.3 ECR API VPCエンドポイント（Interface型）、ECR Docker VPCエンドポイント（Interface型）、S3 Gateway VPCエンドポイントを NetworkConstruct に追加する
- [x] 1.4 `test/constructs/network.test.ts` を更新し、新規 VPCエンドポイント・SG ルールのユニットテストを追加する

## 2. ECS Fargate タスク定義（BulkIngestConstruct）

- [x] 2.1 `ecs/bulk-ingest/` ディレクトリに Dockerfile、requirements.txt、Python ソースコード（main.py, vector_generator.py, ingestion.py, index_manager.py, metrics.py）を作成する
- [x] 2.2 `lib/constructs/bulk-ingest.ts` に BulkIngestConstruct を作成する（ECS クラスター、タスク定義、コンテナイメージ、IAM ロール、環境変数、ログ設定）
- [x] 2.3 `lib/vector-db-benchmark-stack.ts` に BulkIngestConstruct を追加し、依存関係と cdk-nag suppressions を設定する
- [x] 2.4 `test/constructs/bulk-ingest.test.ts` にユニットテストを作成する（タスク定義、メモリ/vCPU、IAM 権限、環境変数、ログ設定）

## 3. 検索テスト Lambda（SearchTestConstruct）

- [x] 3.1 `functions/search-test/` ディレクトリに handler.py, logic.py, models.py, vector_generator.py, requirements.txt を作成する
- [x] 3.2 `template.yaml` に SearchTestFunction エントリを追加する
- [x] 3.3 `lib/constructs/search-test.ts` に SearchTestConstruct を作成する（Lambda 関数、IAM ロール、VPC 配置、環境変数）
- [x] 3.4 `lib/vector-db-benchmark-stack.ts` に SearchTestConstruct を追加し、依存関係と cdk-nag suppressions を設定する
- [x] 3.5 `test/constructs/search-test.test.ts` にユニットテストを作成する（Lambda 構成、IAM 権限、環境変数、メモリ/タイムアウト）

## 4. 決定論的ベクトル生成とメトリクス算出

- [x] 4.1 `ecs/bulk-ingest/vector_generator.py` と `functions/search-test/vector_generator.py` に決定論的ベクトル生成ロジックを実装する（共通ロジック）
- [x] 4.2 `ecs/bulk-ingest/metrics.py` にスループット算出ロジック、`functions/search-test/logic.py` にレイテンシ統計算出ロジックを実装する
- [x] 4.3 プロパティテストを作成する: Property 1（ベクトル生成の正確性・決定論性）、Property 8（クエリベクトル再生成ラウンドトリップ）を `tests/ecs/bulk_ingest/test_vector_generator.py` に実装する
- [x] 4.4 プロパティテストを作成する: Property 3（スループット算出）、Property 5（レイテンシ統計算出）、Property 6（フェーズ所要時間合計）を `tests/ecs/bulk_ingest/test_metrics.py` と `tests/functions/search_test/test_logic.py` に実装する

## 5. インデックス戦略とデータ投入ロジック

- [x] 5.1 `ecs/bulk-ingest/index_manager.py` にインデックス削除・再作成ロジックを実装する（Aurora: DROP/CREATE INDEX、OpenSearch: delete/create index、S3 Vectors: 操作なし）
- [x] 5.2 `ecs/bulk-ingest/ingestion.py` にバッチ投入ロジックを実装する（Aurora: バッチ INSERT 1000件単位、OpenSearch: Bulk API、S3 Vectors: PutVectors バッチ）
- [x] 5.3 `ecs/bulk-ingest/main.py` にエントリポイントを実装する（パラメータ読み取り、3DB 順次実行、エラーハンドリング、メトリクス出力）
- [x] 5.4 `tests/ecs/bulk_ingest/test_ingestion.py` にユニットテストを作成する（バッチ投入、リトライ、エラーハンドリング）
- [x] 5.5 `tests/ecs/bulk_ingest/test_index_manager.py` にユニットテストを作成する（インデックス削除→投入→再作成の順序検証）
- [x] 5.6 プロパティテストを作成する: Property 2（バッチ投入呼び出し回数）を `tests/ecs/bulk_ingest/test_ingestion.py` に実装する

## 6. 検索テスト Lambda ロジック

- [x] 6.1 `functions/search-test/logic.py` に検索ロジックを実装する（3DB 順次検索、レイテンシ計測、統計算出、比較表生成）
- [x] 6.2 `functions/search-test/handler.py` にハンドラーを実装する（パラメータ読み取り、デフォルト値、エラーハンドリング）
- [x] 6.3 `tests/functions/search_test/test_logic.py` にユニットテストを作成する（検索ロジック、エラーハンドリング）
- [x] 6.4 `tests/functions/search_test/test_handler.py` にユニットテストを作成する（パラメータバリデーション、デフォルト値）
- [x] 6.5 プロパティテストを作成する: Property 4（検索クエリ実行回数）を `tests/functions/search_test/test_logic.py` に実装する

## 7. 統合テストと削除ポリシー

- [x] 7.1 `test/integration/stack-nag.test.ts` を更新し、新規リソース（ECS、検索テスト Lambda、ECR）の cdk-nag テストを追加する
- [x] 7.2 `test/integration/stack-properties.test.ts` を更新し、Property 7（全リソース削除ポリシー）のプロパティテストを追加する

