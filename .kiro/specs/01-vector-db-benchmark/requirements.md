# 要件定義書

## はじめに

AWS環境において、Aurora Serverless v2 (pgvector)、OpenSearch Serverless (ベクトルエンジン)、Amazon S3 Vectors の3つのベクトルデータベースリソースを構築し、最小限のデータ投入・検索による動作確認を行う。すべての通信をVPC内に閉じたセキュアな経路で構成し、環境は短期集中で構築・確認・破棄するサイクルを徹底する。本Specではリソース構築とアーキテクチャ構成図の作成、および動作確認までをスコープとし、大量データによる本格的なベンチマーク実行は別Specで対応する。

なお、Aurora pgvectorおよびOpenSearch ServerlessではHNSWアルゴリズムを明示的に指定してインデックスを構築するが、S3 Vectorsはベクトルインデックスのアルゴリズムを利用者が指定できず内部で自動最適化される。このため3者間の厳密なアルゴリズム比較は成立しないが、ANNクエリの動作確認という観点では許容する。

## スコープ外（別Specで対応）

- ECS Fargateによる大量データ投入（10万件）
- Lambda並列負荷テスト
- メトリクス収集と比較表作成
- 本格的なベンチマーク実行

## 用語集

- **ベンチマーク基盤システム**: 本Specにおける全体システム（CDKスタック、動作確認用Lambda関数、ターゲットデータベースを含む）
- **CDKスタック**: AWS CDK v2 (TypeScript) で定義されるインフラストラクチャ一式
- **動作確認Lambda**: 数件のダミーベクトルを投入し検索が動作することを確認するAWS Lambda関数
- **Auroraクラスター**: Amazon Aurora Serverless v2 (PostgreSQL + pgvector拡張) のクラスター
- **OpenSearchコレクション**: Amazon OpenSearch Serverless のベクトル検索コレクション
- **S3ベクトルバケット**: Amazon S3 Vectors のベクトルバケット（ベクトルデータの格納単位）
- **S3ベクトルインデックス**: S3ベクトルバケット内に作成されるベクトルインデックス（次元数・距離メトリクスを定義）
- **ダミーベクトル**: Pythonスクリプト内で動的に生成される1536次元のランダム数値配列
- **ACU**: Aurora Capacity Unit（Aurora Serverless v2 のスケーリング単位）
- **OCU**: OpenSearch Compute Unit（OpenSearch Serverless のスケーリング単位）
- **VPCエンドポイント**: AWS PrivateLinkを利用したインターフェイス型VPCエンドポイント
- **ANNクエリ**: 近似最近傍探索（Approximate Nearest Neighbor）によるベクトル検索クエリ
- **s3vectorsクライアント**: boto3のs3vectorsサービスクライアント（S3 Vectors専用API操作に使用）

## 要件

### 要件 1: VPCネットワーク基盤の構築

**ユーザーストーリー:** インフラ担当者として、すべてのリソースをVPC内のプライベートサブネットに配置したい。セキュアな通信経路を確保し、後続のベンチマーク検証にも再利用可能なネットワーク基盤を構築するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL プライベートサブネットを持つVPCを作成する
2. THE CDKスタック SHALL NAT Gatewayを含まないVPC構成を作成する
3. THE CDKスタック SHALL Auroraクラスターへのアクセスに必要なVPCエンドポイントを作成する
4. THE CDKスタック SHALL OpenSearchコレクションへのアクセスに必要なVPCエンドポイントを作成する
5. THE CDKスタック SHALL S3 Vectorsへのアクセスに必要なVPCエンドポイント（com.amazonaws.{region}.s3vectors）を作成する
6. THE CDKスタック SHALL 動作確認LambdaがAWSサービスAPIを呼び出すために必要なVPCエンドポイント（CloudWatch Logs等）を作成する
7. THE CDKスタック SHALL すべてのリソース名を「awsprivatelab-dev-{サービス名}-{用途}」の命名規則に従って設定する
8. THE CDKスタック SHALL cdk-nagによるセキュリティチェックに合格する構成を生成する

### 要件 2: Aurora Serverless v2 (pgvector) の構築

**ユーザーストーリー:** インフラ担当者として、Aurora Serverless v2にpgvector拡張を有効化した状態でデプロイしたい。ベクトル検索データベースの一つとして構築し、動作確認を行うためである。

#### 受け入れ基準

1. THE CDKスタック SHALL PostgreSQLエンジンのAurora Serverless v2クラスターをプライベートサブネットに作成する
2. THE CDKスタック SHALL AuroraクラスターのMin ACUを0.0、Max ACUを10.0に設定する
3. THE CDKスタック SHALL Auroraクラスターの削除ポリシーをDESTROYに設定し、最終スナップショットの作成をスキップする
4. THE CDKスタック SHALL Auroraクラスターへのアクセスを動作確認Lambdaのセキュリティグループからのみ許可する
5. WHEN 動作確認LambdaがAuroraクラスターに初回接続した際、THE 動作確認Lambda SHALL pgvector拡張を有効化しベクトル格納用テーブルおよびHNSWインデックスを作成する

### 要件 3: OpenSearch Serverless (ベクトルエンジン) の構築

**ユーザーストーリー:** インフラ担当者として、OpenSearch Serverlessのベクトル検索コレクションをデプロイしたい。ベクトル検索データベースのもう一つとして構築し、動作確認を行うためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ベクトル検索タイプのOpenSearch Serverlessコレクションを作成する
2. THE CDKスタック SHALL OpenSearchコレクションへのアクセス用にVPCエンドポイント（AWS PrivateLink）を作成する
3. THE CDKスタック SHALL OpenSearch ServerlessのMax OCUをインデックス用・検索用それぞれ4以上8以下に制限する
4. THE CDKスタック SHALL OpenSearchコレクションの暗号化ポリシー、ネットワークポリシー、データアクセスポリシーを設定する
5. THE CDKスタック SHALL OpenSearchコレクションへのアクセスを動作確認LambdaのIAMロールからのみ許可する

### 要件 3a: Amazon S3 Vectors の構築

**ユーザーストーリー:** インフラ担当者として、Amazon S3 Vectorsのベクトルバケットおよびベクトルインデックスをデプロイしたい。3つ目のベクトル検索対象として構築し、Aurora pgvectorおよびOpenSearch Serverlessとの動作比較を行うためである。

#### 受け入れ基準

1. THE CDKスタック SHALL S3 Vectorsのベクトルバケット（awsprivatelab-dev-s3vectors-benchmark）をCfnVectorBucketで作成する
2. THE CDKスタック SHALL ベクトルバケット内にベクトルインデックス（embeddings）をCfnIndexで作成する
3. THE CDKスタック SHALL ベクトルインデックスの次元数を1536、距離メトリクスをcosine、データ型をfloat32に設定する
4. THE CDKスタック SHALL S3 Vectorsへのアクセス用にVPCエンドポイント（com.amazonaws.{region}.s3vectors、Interface型）を作成する
5. THE CDKスタック SHALL 動作確認LambdaのIAMロールにs3vectors名前空間の必要な権限（PutVectors、GetVectors、QueryVectors、DeleteVectors）を付与する
6. THE CDKスタック SHALL ベクトルバケットおよびベクトルインデックスの削除ポリシーをDESTROYに設定する

### 要件 4: アーキテクチャ構成図の作成

**ユーザーストーリー:** インフラ担当者として、構築するシステムのアーキテクチャ構成図を作成したい。リソース間の関係性とネットワーク構成を視覚的に把握するためである。

#### 受け入れ基準

1. THE ベンチマーク基盤システム SHALL VPC、サブネット、VPCエンドポイント、Auroraクラスター、OpenSearchコレクション、S3ベクトルバケット、動作確認Lambdaの配置を示す構成図を含む
2. THE 構成図 SHALL draw.io形式（.drawio）で作成しdocsディレクトリに配置する
3. THE 構成図 SHALL セキュリティグループの境界とネットワーク経路を明示する
4. THE 構成図 SHALL S3 VectorsへのVPCエンドポイント経由の通信経路を明示する

### 要件 5: 最小限のデータ投入と検索による動作確認

**ユーザーストーリー:** 検証担当者として、各データベースに数件のダミーベクトルを投入し検索が動作することを確認したい。リソースが正しく構築され接続・投入・検索の一連の流れが機能することを検証するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL 動作確認用のLambda関数をプライベートサブネットに作成する
2. THE CDKスタック SHALL 動作確認LambdaのIAMロールにAuroraクラスター、OpenSearchコレクション、およびS3 Vectorsへのアクセス権限を付与する
3. WHEN 動作確認Lambdaが実行された際、THE 動作確認Lambda SHALL 1536次元のダミーベクトルを数件（5件程度）プログラム内で動的に生成する
4. THE 動作確認Lambda SHALL Amazon Bedrock等の外部APIを一切呼び出さずにダミーベクトルを生成する
5. WHEN 動作確認Lambdaが実行された際、THE 動作確認Lambda SHALL 生成したダミーベクトルをAuroraクラスターに投入する
6. WHEN 動作確認Lambdaが実行された際、THE 動作確認Lambda SHALL 生成したダミーベクトルをOpenSearchコレクションに投入する
7. WHEN 動作確認Lambdaが実行された際、THE 動作確認Lambda SHALL 生成したダミーベクトルをS3 Vectorsにboto3のs3vectorsクライアント経由でPutVectorsにより投入する
8. WHEN データ投入が完了した際、THE 動作確認Lambda SHALL ランダムなクエリベクトルを生成しAuroraクラスターに対してANNクエリを実行する
9. WHEN データ投入が完了した際、THE 動作確認Lambda SHALL ランダムなクエリベクトルを生成しOpenSearchコレクションに対してANNクエリを実行する
10. WHEN データ投入が完了した際、THE 動作確認Lambda SHALL ランダムなクエリベクトルを生成しS3 Vectorsに対してQueryVectorsによるANNクエリを実行する
11. THE 動作確認Lambda SHALL 3つのデータベースそれぞれの投入件数と検索結果件数をレスポンスに含め、接続・投入・検索の成否を判定可能とする

### 要件 6: 環境の安全な破棄

**ユーザーストーリー:** インフラ担当者として、確認完了後に `cdk destroy` で全リソースを跡形もなく削除したい。環境維持による無駄なコストをゼロにするためである。

#### 受け入れ基準

1. THE CDKスタック SHALL すべてのリソースにremovalPolicy: DESTROYを設定する
2. THE CDKスタック SHALL Auroraクラスターの最終スナップショット作成をスキップする設定を含む
3. THE CDKスタック SHALL `cdk destroy` の実行により全リソースが削除される構成とする
4. IF `cdk destroy` の実行中にリソース削除が失敗した場合、THEN THE CDKスタック SHALL 削除を妨げるリソース依存関係を持たない構成とする
5. WHEN S3ベクトルバケットを削除する際、THE CDKスタック SHALL ベクトルインデックス内のデータおよびベクトルインデックスが先に削除される依存関係を設定する

### 要件 7: セキュリティとコスト保護

**ユーザーストーリー:** インフラ担当者として、セキュリティベストプラクティスを遵守しつつ青天井の課金を防止したい。検証環境であっても安全かつコスト管理された状態を維持するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL cdk-nagによるセキュリティチェックに合格する構成を生成する
2. THE CDKスタック SHALL すべてのデータベース通信をVPC内のプライベート経路に限定する
3. THE CDKスタック SHALL Aurora Serverless v2のMax ACUを10.0以下に制限する
4. THE CDKスタック SHALL OpenSearch ServerlessのMax OCUを8以下に制限する
5. THE CDKスタック SHALL NAT Gatewayを使用せずVPCエンドポイント経由でAWSサービスにアクセスする構成とする
6. THE 動作確認Lambda SHALL Amazon Bedrock等の外部APIを呼び出さずダミーベクトル生成によりAPI費用を発生させない構成とする
7. THE CDKスタック SHALL S3 Vectorsへのアクセスを動作確認LambdaのIAMロールに限定し、必要最小限のs3vectors権限のみ付与する
8. THE CDKスタック SHALL S3 VectorsへのアクセスをVPCエンドポイント経由のプライベート経路に限定する
