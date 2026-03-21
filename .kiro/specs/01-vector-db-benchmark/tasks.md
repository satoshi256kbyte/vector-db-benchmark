# タスク一覧

## タスク 1: NetworkConstruct の実装

- [x] 1.1 `lib/constructs/network.ts` に NetworkConstruct を作成する
  - VPC（CIDR: 10.0.0.0/16、2 AZ、ISOLATEDサブネットのみ、NAT Gateway なし）
  - セキュリティグループ 3つ（Lambda用、Aurora用、VPCエンドポイント用）
  - セキュリティグループルール（Lambda→Aurora:5432、Lambda→VPC EP:443）
  - VPCエンドポイント（Secrets Manager、CloudWatch Logs、OpenSearch Serverless）
  - 命名規則: `awsprivatelab-dev-*`
- [x] 1.2 `test/constructs/network.test.ts` に NetworkConstruct のユニットテストを作成する
  - VPC作成の検証
  - NAT Gateway が存在しないことの検証
  - VPCエンドポイント 3つの存在検証
  - セキュリティグループルールの検証

## タスク 2: AuroraConstruct の実装

- [x] 2.1 `lib/constructs/aurora.ts` に AuroraConstruct を作成する
  - Aurora Serverless v2 クラスター（PostgreSQL 16.x）
  - ACU: Min 0.5 / Max 16.0
  - プライベートサブネット配置
  - Secrets Manager による認証情報自動生成
  - removalPolicy: DESTROY、スナップショットスキップ
  - セキュリティグループ: Lambda SG からの 5432 のみ許可
  - 命名規則: `awsprivatelab-dev-aurora-pgvector`
- [x] 2.2 `test/constructs/aurora.test.ts` に AuroraConstruct のユニットテストを作成する
  - Aurora クラスター作成の検証
  - Serverless v2 スケーリング設定（Min/Max ACU）の検証
  - 削除ポリシー DESTROY の検証
  - セキュリティグループインバウンドルールの検証

## タスク 3: OpenSearchConstruct の実装

- [x] 3.1 `lib/constructs/opensearch.ts` に OpenSearchConstruct を作成する
  - OpenSearch Serverless コレクション（VECTORSEARCH タイプ）
  - 暗号化ポリシー（AWS所有キー）
  - ネットワークポリシー（VPCエンドポイント経由のみ）
  - データアクセスポリシー（Lambda IAMロールのみ許可）
  - OCU制限: CfnAccountSettings でインデックス用・検索用それぞれ Max 4
  - 命名規則: `awsprivatelab-dev-oss-vector`
- [x] 3.2 `test/constructs/opensearch.test.ts` に OpenSearchConstruct のユニットテストを作成する
  - コレクション作成（VECTORSEARCH タイプ）の検証
  - 暗号化ポリシーの検証
  - ネットワークポリシーの検証
  - データアクセスポリシーの検証

## タスク 4: 動作確認 Lambda 関数の実装（Python）

- [x] 4.1 `functions/vector-verify/models.py` にデータモデルを作成する
  - DatabaseResult dataclass
  - VerifyResponse dataclass
  - 型ヒント必須、ruff/mypy 準拠
- [x] 4.2 `functions/vector-verify/logic.py` にビジネスロジックを作成する
  - generate_dummy_vectors(): ダミーベクトル生成（random モジュール使用）
  - init_aurora_pgvector(): pgvector 拡張有効化 + テーブル/インデックス作成
  - insert_aurora_vectors(): Aurora へのベクトル投入
  - search_aurora_vectors(): Aurora での ANN クエリ実行
  - insert_opensearch_vectors(): OpenSearch へのベクトル投入
  - search_opensearch_vectors(): OpenSearch での ANN クエリ実行
  - Powertools Logger/Tracer 使用
- [x] 4.3 `functions/vector-verify/handler.py` に Lambda ハンドラーを作成する
  - Powertools デコレータ適用
  - Aurora / OpenSearch それぞれの動作確認実行
  - エラーハンドリング（各DB独立して実行、片方失敗しても他方は継続）
  - VerifyResponse を JSON で返却
- [x] 4.4 `functions/vector-verify/requirements.txt` に依存ライブラリを定義する
  - aws-lambda-powertools
  - psycopg2-binary（Aurora接続）
  - opensearch-py（OpenSearch接続）
  - boto3

## タスク 5: VerifyFunctionConstruct の実装

- [x] 5.1 `lib/constructs/verify-function.ts` に VerifyFunctionConstruct を作成する
  - Lambda 関数（Python 3.13、256MB、タイムアウト 300秒）
  - プライベートサブネット配置、Lambda SG 適用
  - IAMロール: Secrets Manager 読み取り、OpenSearch aoss:APIAccessAll
  - 環境変数設定（AURORA_SECRET_ARN、AURORA_CLUSTER_ENDPOINT、OPENSEARCH_ENDPOINT、POWERTOOLS_*）
  - 命名規則: `awsprivatelab-dev-lambda-vector-verify`
- [x] 5.2 `test/constructs/verify-function.test.ts` に VerifyFunctionConstruct のユニットテストを作成する
  - Lambda 関数作成の検証（ランタイム、メモリ、タイムアウト）
  - VPC 配置の検証
  - IAM ポリシーの検証
  - 環境変数の検証

## タスク 6: スタック統合と cdk-nag 対応

- [x] 6.1 `lib/aws-private-lab-stack.ts` を更新し全 Construct を統合する
  - NetworkConstruct、AuroraConstruct、OpenSearchConstruct、VerifyFunctionConstruct のインスタンス化
  - Construct 間の依存関係設定
  - cdk-nag Aspects の適用
- [x] 6.2 `bin/aws-private-lab.ts` に cdk-nag の AwsSolutionsChecks を追加する
- [x] 6.3 `test/integration/stack-nag.test.ts` に cdk-nag 統合テストを作成する
  - AwsSolutionsChecks でエラーが発生しないことの検証
  - 必要な NagSuppressions の追加と理由コメント

## タスク 7: プロパティテストの実装

- [x] 7.1 `test/integration/stack-properties.test.ts` に CDK プロパティテストを作成する
  - プロパティ 1: リソース命名規則の一貫性（テンプレート内の全リソース名を走査）
  - プロパティ 4: 全リソースの削除ポリシー（DeletionPolicy: Delete の検証）
- [x] 7.2 `tests/functions/vector_verify/test_models.py` に Python プロパティテストを作成する
  - プロパティ 2: ダミーベクトル生成の正確性（Hypothesis 使用、100回イテレーション）
  - プロパティ 3: レスポンスモデルの完全性（Hypothesis 使用、100回イテレーション）
- [x] 7.3 `tests/functions/vector_verify/test_logic.py` にビジネスロジックのユニットテストを作成する
  - generate_dummy_vectors のエッジケーステスト
  - Aurora/OpenSearch 操作のモックテスト

## タスク 8: アーキテクチャ構成図の作成

- [x] 8.1 `docs/architecture-vector-benchmark.drawio` に draw.io 形式の構成図を作成する
  - VPC 境界とサブネット配置
  - セキュリティグループの境界
  - VPC エンドポイントの接続経路
  - Aurora クラスターと OpenSearch コレクションの配置
  - Lambda 関数からの通信経路

## タスク 9: S3VectorsConstruct の実装

- [x] 9.1 `lib/constructs/s3vectors.ts` に S3VectorsConstruct を作成する
  - CfnVectorBucket（名前: `awsprivatelab-dev-s3vectors-benchmark`）
  - CfnIndex（名前: `embeddings`、dimension: 1536、distanceMetric: cosine、dataType: float32）
  - RemovalPolicy.DESTROY をバケット・インデックス両方に適用
  - 依存関係: インデックスはバケットに依存（`addDependency`）
  - `vectorBucketName` と `indexName` を readonly プロパティとして公開
  - _要件: 3a.1, 3a.2, 3a.3, 3a.6_
- [x] 9.2 `test/constructs/s3vectors.test.ts` に S3VectorsConstruct のユニットテストを作成する
  - CfnVectorBucket 作成の検証
  - CfnIndex 作成の検証（dimension: 1536、distanceMetric: cosine、dataType: float32）
  - DeletionPolicy: Delete がバケット・インデックス両方に設定されていることの検証
  - インデックスからバケットへの依存関係の検証
  - _要件: 3a.1, 3a.2, 3a.3, 3a.6_

## タスク 10: NetworkConstruct の更新（S3 Vectors VPCエンドポイント追加）

- [x] 10.1 `lib/constructs/network.ts` に S3 Vectors 用 VPC エンドポイントを追加する
  - Interface VPC エンドポイント: `com.amazonaws.{region}.s3vectors`
  - 既存の OpenSearch Serverless エンドポイントと同じパターンで追加
  - _要件: 1.5, 3a.4, 7.8_
- [x] 10.2 `test/constructs/network.test.ts` を更新し S3 Vectors VPC エンドポイントを検証する
  - 新しい VPC エンドポイントの存在検証
  - _要件: 1.5_

## タスク 11: Lambda 関数の更新（S3 Vectors 対応）

- [x] 11.1 `functions/vector-verify/models.py` を更新する
  - VerifyResponse に `s3vectors: DatabaseResult` フィールドを追加
  - DatabaseResult の docstring に `"s3vectors"` を追加
  - _要件: 5.11, プロパティ 3_
- [x] 11.2 `functions/vector-verify/logic.py` を更新する
  - S3 Vectors 定数を追加（`S3VECTORS_BUCKET_NAME`、`S3VECTORS_INDEX_NAME` を環境変数から取得）
  - `insert_s3vectors_vectors()` 関数を追加（boto3 s3vectors クライアントの PutVectors API 使用）
  - `search_s3vectors_vectors()` 関数を追加（boto3 s3vectors クライアントの QueryVectors API 使用）
  - `run_s3vectors_verify()` 関数を追加（run_aurora_verify / run_opensearch_verify と同パターン）
  - _要件: 5.7, 5.10_
- [x] 11.3 `functions/vector-verify/handler.py` を更新する
  - `run_s3vectors_verify` を logic からインポート
  - S3 Vectors 動作確認ブロックを追加（独立実行、Aurora/OpenSearch と同パターン）
  - VerifyResponse 構築に `s3vectors` 結果を含める
  - _要件: 5.7, 5.10, 5.11_
- [x] 11.4 `functions/vector-verify/requirements.txt` を確認・更新する
  - boto3 が既に含まれていることを確認（s3vectors クライアントは boto3 に含まれる）
  - _要件: 5.7_

## タスク 12: チェックポイント - S3 Vectors Lambda ロジックの確認

- [x] 12. すべてのテストが pass することを確認し、不明点があればユーザーに質問する

## タスク 13: VerifyFunctionConstruct の更新（S3 Vectors 対応）

- [x] 13.1 `lib/constructs/verify-function.ts` を更新する
  - props に `s3vectorsBucketName` と `s3vectorsIndexName` を追加
  - 環境変数 `S3VECTORS_BUCKET_NAME` と `S3VECTORS_INDEX_NAME` を追加
  - IAM ポリシーに `s3vectors:PutVectors`、`s3vectors:GetVectors`、`s3vectors:QueryVectors`、`s3vectors:DeleteVectors` を追加
  - _要件: 5.2, 3a.5, 7.7, 設計書 VerifyFunctionConstruct_
- [x] 13.2 `test/constructs/verify-function.test.ts` を更新する
  - S3 Vectors 環境変数の検証
  - s3vectors IAM 権限の検証
  - _要件: 5.2, 3a.5_

## タスク 14: スタック統合の更新（S3 Vectors 追加）

- [x] 14.1 `lib/aws-private-lab-stack.ts` を更新する
  - S3VectorsConstruct をインポート・インスタンス化
  - `s3vectorsBucketName` と `s3vectorsIndexName` を VerifyFunctionConstruct に渡す
  - 依存関係: verifyFunction は s3vectors に依存
  - 必要な cdk-nag suppressions を追加
  - _要件: 3a, 設計書_

## タスク 15: テストの更新（S3 Vectors 対応）

- [x] 15.1 `tests/functions/vector_verify/test_models.py` を更新する
  - VerifyResponse のプロパティテストに `s3vectors` フィールドを追加
  - **プロパティ 3: レスポンスモデルの完全性**
  - **検証対象: 要件 5.11**
- [x] 15.2 `tests/functions/vector_verify/test_logic.py` を更新する
  - S3 Vectors の insert/search 関数のユニットテストを追加（boto3 s3vectors クライアントをモック）
  - `run_s3vectors_verify` のユニットテストを追加
  - _要件: 5.7, 5.10_
- [x] 15.3 `test/integration/stack-properties.test.ts` を更新する
  - S3 Vectors リソースが命名規則に従っていることを検証（プロパティ 1）
  - S3 Vectors リソースに DeletionPolicy: Delete が設定されていることを検証（プロパティ 4）
  - **プロパティ 1: リソース命名規則の一貫性**
  - **プロパティ 4: 全リソースの削除ポリシー**
  - **検証対象: 要件 1.7, 3a.6**
- [x] 15.4 `test/integration/stack-nag.test.ts` を更新する
  - S3 Vectors リソース追加後も cdk-nag が pass することを確認
  - _要件: 1.8, 7.1_

## タスク 16: チェックポイント - 全テスト pass 確認

- [x] 16. すべてのテスト（Jest + pytest）が pass することを確認し、不明点があればユーザーに質問する

## タスク 17: アーキテクチャ構成図の更新

- [x] 17.1 `docs/architecture-vector-benchmark.drawio` を更新する
  - S3 Vectors（awsprivatelab-dev-s3vectors-benchmark）を構成図に追加
  - S3 Vectors VPC エンドポイント（com.amazonaws.{region}.s3vectors）を追加
  - Lambda から S3 Vectors への VPC エンドポイント経由の通信経路を追加
  - _要件: 4.1, 4.4_
