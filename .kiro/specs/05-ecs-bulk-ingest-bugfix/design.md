# ECS 一括投入バグ修正 設計ドキュメント

## 概要

ECS Fargate タスクによるベクトルデータ一括投入において、2つのバグが存在する:

1. **Aurora テーブル未存在エラー**: 初回実行時に `embeddings` テーブルが存在しないため、`TRUNCATE TABLE` や `INSERT INTO` が失敗する。pgvector 拡張の未インストールも考慮が必要。
2. **OpenSearch Serverless 接続失敗**: ISOLATED サブネットの ECS タスクから OpenSearch Serverless コレクションへの接続がタイムアウトする。`network.ts` に `aoss` 用 Interface VPC Endpoint が存在するが、OpenSearch Serverless の `CfnVpcEndpoint`（`opensearch.ts`）との重複が DNS 解決の競合を引き起こしている可能性がある。

修正方針は最小限の変更で、既存の正常動作を維持しつつバグを解消する。

## 用語集

- **Bug_Condition (C)**: バグを引き起こす条件。Aurora テーブル未存在時の SQL 実行、または OpenSearch Serverless への接続失敗
- **Property (P)**: バグ条件下での期待される正常動作。テーブル自動作成後の正常実行、または VPC エンドポイント経由の正常接続
- **Preservation**: 修正によって変更されてはならない既存動作。テーブル存在時の TRUNCATE/INSERT、S3 Vectors 操作、count モードのエラーハンドリング等
- **`AuroraIndexManager`**: `ecs/bulk-ingest/index_manager.py` の Aurora HNSW インデックス管理クラス
- **`AuroraIngester`**: `ecs/bulk-ingest/ingestion.py` の Aurora バッチ INSERT クラス
- **`ensure_table()`**: 追加予定のメソッド。pgvector 拡張の有効化と `embeddings` テーブルの自動作成を行う
- **`CfnVpcEndpoint`**: OpenSearch Serverless 固有の VPC エンドポイント（`opensearch.ts` で作成）
- **Interface VPC Endpoint (`aoss`)**: `network.ts` で作成される標準 AWS Interface VPC Endpoint

## バグ詳細

### バグ条件

2つの独立したバグ条件が存在する:

**バグ 1: Aurora テーブル未存在**

初回実行時または `embeddings` テーブルが削除された後に、`index_drop` モードまたは `ingest` モードで Aurora を対象に ECS タスクを実行すると、テーブル未存在エラーで異常終了する。pgvector 拡張が未インストールの場合も `vector` 型が認識されず失敗する。

**形式仕様:**
```
FUNCTION isBugCondition_Aurora(input)
  INPUT: input of type ECSTaskConfig {target_db, task_mode}
  OUTPUT: boolean

  RETURN input.target_db == "aurora"
         AND input.task_mode IN ["index_drop", "ingest"]
         AND NOT tableExists("embeddings")
END FUNCTION
```

**バグ 2: OpenSearch Serverless 接続失敗**

ECS タスクから OpenSearch Serverless コレクションに接続しようとすると、VPC エンドポイント経由の接続が失敗する。`network.ts` の `aoss` Interface VPC Endpoint と `opensearch.ts` の `CfnVpcEndpoint` が重複しており、DNS 解決が正しい VPC エンドポイントに向かない可能性がある。

**形式仕様:**
```
FUNCTION isBugCondition_OpenSearch(input)
  INPUT: input of type ECSTaskConfig {target_db, task_mode}
  OUTPUT: boolean

  RETURN input.target_db IN ["opensearch", "all"]
         AND input.task_mode IN ["ingest", "index_drop", "index_create", "count"]
         AND ecsTaskRunsInIsolatedSubnet()
         AND opensearchConnectionFails()
END FUNCTION
```

### 具体例

- **例 1**: `TASK_MODE=index_drop`, `TARGET_DB=aurora`, テーブル未存在 → `TRUNCATE TABLE embeddings` で `relation "embeddings" does not exist` エラー
- **例 2**: `TASK_MODE=ingest`, `TARGET_DB=aurora`, テーブル未存在 → `INSERT INTO embeddings` でテーブル未存在エラー
- **例 3**: `TASK_MODE=ingest`, `TARGET_DB=aurora`, pgvector 未インストール → `vector` 型不明エラー
- **例 4**: `TASK_MODE=ingest`, `TARGET_DB=opensearch` → `OpenSearch connection failed after 3 retries` で接続タイムアウト
- **エッジケース**: `TASK_MODE=count`, `TARGET_DB=aurora`, テーブル未存在 → 既存ハンドリングで count=0（これは正常動作、変更不要）

## 期待される動作

### 保全要件

**変更されない動作:**
- `embeddings` テーブルが既に存在する場合の `drop_index()` の TRUNCATE 動作
- `embeddings` テーブルが既に存在する場合の `ingest_batch()` の INSERT 動作
- `_run_count_operation()` の既存テーブル未存在ハンドリング（`does not exist` → count=0）
- `AuroraIndexManager.create_index()` の HNSW インデックス作成動作
- S3 Vectors への接続とデータ投入
- `_run_count_operation()` の OpenSearch インデックス未存在ハンドリング（`index_not_found_exception` → count=0）
- `_run_all_databases()` の全 DB 順次処理フロー

**スコープ:**
バグ条件に該当しない入力（テーブル存在時の Aurora 操作、S3 Vectors 操作、count モードのエラーハンドリング）は修正の影響を受けない。

## 仮説的根本原因

### バグ 1: Aurora テーブル未存在

1. **`ensure_table()` メソッドの欠如**: `AuroraIndexManager` と `AuroraIngester` のどちらにも、テーブルの存在確認・自動作成ロジックがない。`drop_index()` は `TRUNCATE TABLE embeddings` を無条件に実行し、`ingest_batch()` は `INSERT INTO embeddings` を無条件に実行する。
2. **pgvector 拡張の未インストール**: Aurora PostgreSQL に pgvector 拡張がインストールされていない場合、`CREATE TABLE` で `vector` 型を使用できない。`CREATE EXTENSION IF NOT EXISTS vector` の事前実行が必要。

### バグ 2: OpenSearch Serverless 接続失敗

1. **VPC エンドポイントの重複**: `network.ts` が `com.amazonaws.${region}.aoss` の Interface VPC Endpoint を作成し、`opensearch.ts` が `CfnVpcEndpoint` を作成している。両方が同じ `aoss` サービス向けだが、OpenSearch Serverless のネットワークポリシーは `CfnVpcEndpoint` の ID のみを許可している。DNS 解決が `network.ts` 側の Interface VPC Endpoint に向かうと、ネットワークポリシーで拒否される可能性がある。
2. **Interface VPC Endpoint の不要性**: OpenSearch Serverless は `CfnVpcEndpoint` を使用する独自の VPC エンドポイントメカニズムを持つ。`network.ts` の標準 Interface VPC Endpoint は不要であり、削除することで DNS 解決の競合を解消できる。

## 正確性プロパティ

Property 1: Bug Condition - Aurora テーブル自動作成

_For any_ ECS タスク実行で `TARGET_DB=aurora` かつ `TASK_MODE` が `index_drop` または `ingest` であり、`embeddings` テーブルが存在しない場合、修正後のコードは pgvector 拡張の有効化とテーブルの自動作成を行い、後続の SQL 操作が正常に完了する。

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Condition - OpenSearch Serverless 接続成功

_For any_ ECS タスク実行で `TARGET_DB=opensearch` であり、ISOLATED サブネットから実行される場合、修正後の CDK コードにより VPC エンドポイント経由で OpenSearch Serverless コレクションに正常に接続できる。

**Validates: Requirements 2.4**

Property 3: Preservation - 既存 Aurora 動作の維持

_For any_ ECS タスク実行で `embeddings` テーブルが既に存在する場合、修正後のコードは修正前と同一の動作を行い、`drop_index()` の TRUNCATE、`ingest_batch()` の INSERT、`create_index()` の HNSW インデックス作成がすべて従来通り正常に動作する。

**Validates: Requirements 3.1, 3.2, 3.4**

Property 4: Preservation - 既存エラーハンドリングと他 DB 動作の維持

_For any_ ECS タスク実行で `TASK_MODE=count` の場合、または `TARGET_DB=s3vectors` の場合、修正後のコードは修正前と同一の動作を行い、既存のエラーハンドリング（テーブル/インデックス未存在時の count=0）と S3 Vectors 操作が従来通り正常に動作する。

**Validates: Requirements 3.3, 3.5, 3.6, 3.7**

## 修正実装

### 必要な変更

根本原因分析が正しいと仮定した場合:

**ファイル**: `ecs/bulk-ingest/index_manager.py`

**関数**: `AuroraIndexManager`

**具体的な変更**:
1. **`ensure_table()` メソッドの追加**: `CREATE EXTENSION IF NOT EXISTS vector` と `CREATE TABLE IF NOT EXISTS embeddings (content TEXT, embedding vector(1536))` を実行するメソッドを追加
2. **`drop_index()` の修正**: `TRUNCATE TABLE` 実行前にテーブル存在チェックを追加。テーブルが存在しない場合はスキップ（ログ出力のみ）

**ファイル**: `ecs/bulk-ingest/ingestion.py`

**関数**: `AuroraIngester`

**具体的な変更**:
3. **`ingest_all()` の修正**: データ投入開始前に `ensure_table()` を呼び出してテーブルの存在を保証する。`AuroraIngester` の初期化時に `AuroraIndexManager` への参照を持つか、`ensure_table()` を独立関数として実装する

**ファイル**: `ecs/bulk-ingest/main.py`

**具体的な変更**:
4. **`_run_index_operation()` の修正**: Aurora の `index_drop` 実行前に `ensure_table()` を呼び出す（テーブルが存在しない場合の TRUNCATE エラーを防止）
5. **`_run_single_database()` / `_run_all_databases()` の修正**: Aurora のデータ投入前に `ensure_table()` を呼び出す

**ファイル**: `lib/constructs/network.ts`

**具体的な変更**:
6. **`aoss` Interface VPC Endpoint の削除**: `network.ts` から `OpenSearchServerlessEndpoint`（`com.amazonaws.${region}.aoss`）の Interface VPC Endpoint を削除する。OpenSearch Serverless は `opensearch.ts` の `CfnVpcEndpoint` を使用するため、標準 Interface VPC Endpoint は不要であり、DNS 解決の競合を引き起こしている可能性がある

## テスト戦略

### 検証アプローチ

テスト戦略は2段階のアプローチに従う: まず未修正コードでバグを再現する反例を表面化させ、次に修正が正しく機能し既存動作を保全することを検証する。

### 探索的バグ条件チェック

**目的**: 修正実装前にバグを再現する反例を表面化させる。根本原因分析を確認または反証する。反証した場合は再仮説が必要。

**テスト計画**: Aurora テーブル未存在時の SQL 実行をシミュレートし、エラーが発生することを確認する。OpenSearch Serverless への接続テストは CDK デプロイ後の統合テストで確認する。

**テストケース**:
1. **Aurora drop_index テスト**: テーブル未存在時に `drop_index()` を呼び出し、`relation "embeddings" does not exist` エラーが発生することを確認（未修正コードで失敗）
2. **Aurora ingest_batch テスト**: テーブル未存在時に `ingest_batch()` を呼び出し、テーブル未存在エラーが発生することを確認（未修正コードで失敗）
3. **pgvector 未インストールテスト**: pgvector 拡張なしで `CREATE TABLE ... vector(1536)` を実行し、型不明エラーが発生することを確認（未修正コードで失敗）
4. **OpenSearch 接続テスト**: ISOLATED サブネットから OpenSearch Serverless への接続を試行し、タイムアウトすることを確認（CDK デプロイ後の統合テスト）

**期待される反例**:
- Aurora: `psycopg2.errors.UndefinedTable` または同等のエラー
- OpenSearch: 接続タイムアウト（3回リトライ後に `RuntimeError`）

### 修正チェック

**目的**: バグ条件が成立するすべての入力に対して、修正後の関数が期待される動作を生成することを検証する。

**擬似コード:**
```
FOR ALL input WHERE isBugCondition_Aurora(input) DO
  result := ensure_table(connection)
  ASSERT tableExists("embeddings")
  ASSERT extensionExists("vector")
  result := drop_index_fixed(connection) OR ingest_batch_fixed(connection, data)
  ASSERT no_error(result)
END FOR
```

### 保全チェック

**目的**: バグ条件が成立しないすべての入力に対して、修正後の関数が修正前と同一の結果を生成することを検証する。

**擬似コード:**
```
FOR ALL input WHERE NOT isBugCondition_Aurora(input) DO
  ASSERT drop_index_original(input) == drop_index_fixed(input)
  ASSERT ingest_batch_original(input) == ingest_batch_fixed(input)
END FOR
```

**テストアプローチ**: プロパティベーステストは保全チェックに推奨される。多数のテストケースを自動生成し、手動ユニットテストでは見逃すエッジケースを検出し、非バグ入力に対する動作の不変性を強力に保証する。

**テスト計画**: 未修正コードでの動作を先に観察し（テーブル存在時の TRUNCATE/INSERT）、その動作を保全するプロパティベーステストを作成する。

**テストケース**:
1. **Aurora TRUNCATE 保全**: テーブル存在時に `drop_index()` が従来通り TRUNCATE を正常実行することを検証
2. **Aurora INSERT 保全**: テーブル存在時に `ingest_batch()` が従来通り INSERT を正常実行することを検証
3. **count モード保全**: `_run_count_operation()` のテーブル未存在ハンドリングが変更されていないことを検証
4. **S3 Vectors 保全**: S3 Vectors への操作が修正の影響を受けないことを検証

### ユニットテスト

- `ensure_table()` が pgvector 拡張の有効化とテーブル作成を正しく実行することをテスト
- `ensure_table()` がテーブル既存時に冪等に動作する（エラーなし）ことをテスト
- `drop_index()` がテーブル未存在時にエラーなく完了することをテスト
- `drop_index()` がテーブル存在時に従来通り TRUNCATE を実行することをテスト

### プロパティベーステスト

- ランダムなテーブル存在/非存在状態を生成し、`ensure_table()` 後に必ずテーブルが存在することを検証
- ランダムなバッチデータを生成し、`ensure_table()` 後の `ingest_batch()` が正常に完了することを検証
- テーブル存在時の `drop_index()` と `ingest_batch()` が修正前後で同一の動作をすることを検証

### 統合テスト

- CDK デプロイ後に ECS タスクを `TASK_MODE=index_drop`, `TARGET_DB=aurora` で実行し、テーブル未存在時に正常完了することを確認
- CDK デプロイ後に ECS タスクを `TASK_MODE=ingest`, `TARGET_DB=aurora` で実行し、テーブル自動作成後にデータ投入が成功することを確認
- CDK デプロイ後に ECS タスクを `TASK_MODE=ingest`, `TARGET_DB=opensearch` で実行し、VPC エンドポイント経由で接続が成功することを確認
- 全 DB を対象にベンチマークスクリプトを実行し、エンドツーエンドで正常完了することを確認
