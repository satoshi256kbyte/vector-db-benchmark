# 要件定義書

## はじめに

Spec 01（ベクトルDB ベンチマーク基盤）で構築した3つのベクトルデータベース（Aurora pgvector、OpenSearch Serverless、Amazon S3 Vectors）に対して、ECS Fargate タスクで10万件のベクトルデータを一括投入し、Lambda 関数で検索負荷テストを実施する。

データ投入時のパフォーマンス最適化として、Aurora pgvector および OpenSearch Serverless ではインデックスを一旦削除してからデータを投入し、投入完了後にインデックスを再作成する戦略を採用する。S3 Vectors はインデックスアルゴリズムがユーザー指定不可（内部自動最適化）であるため、インデックス削除・再作成の戦略は適用せず、そのままデータを投入する。

現在のVPCはISOLATEDサブネットのみ（NAT Gateway なし）であるため、ECS Fargate タスクがECRイメージをプルするにはVPCエンドポイント（ECR、ECR Docker、S3 Gateway）の追加が必要となる。

## スコープ外

- ベンチマーク結果のダッシュボード化（CloudWatch Dashboard等）
- 複数回のベンチマーク実行の自動化（Step Functions等）
- ベクトルデータの永続保存（投入後の検証が完了したら環境ごと破棄）

## 用語集

- **ベンチマークシステム**: 本Specにおける全体システム（CDKスタック、ECSタスク、検索テストLambda、ターゲットデータベースを含む）
- **CDKスタック**: AWS CDK v2 (TypeScript) で定義されるインフラストラクチャ一式（VectorDbBenchmarkStack）
- **投入ECSタスク**: ECS Fargate上で実行されるPythonコンテナタスク。10万件のベクトルデータを3つのDBに一括投入する
- **検索テストLambda**: 検索負荷テストを実行するAWS Lambda関数。各DBに対してANNクエリを並列実行しレイテンシを計測する
- **Auroraクラスター**: Spec 01で構築済みのAurora Serverless v2 (PostgreSQL + pgvector拡張) クラスター
- **OpenSearchコレクション**: Spec 01で構築済みのOpenSearch Serverless ベクトル検索コレクション
- **S3ベクトルバケット**: Spec 01で構築済みのAmazon S3 Vectorsベクトルバケット
- **HNSWインデックス**: Hierarchical Navigable Small World アルゴリズムによるベクトル検索インデックス
- **バッチサイズ**: 1回のAPI呼び出しで投入するベクトル件数
- **ANNクエリ**: 近似最近傍探索（Approximate Nearest Neighbor）によるベクトル検索クエリ
- **投入メトリクス**: データ投入に関する計測値（所要時間、スループット等）
- **検索メトリクス**: 検索テストに関する計測値（レイテンシ、スループット等）

## 要件

### 要件 1: VPCネットワーク拡張（ECS Fargate対応）

**ユーザーストーリー:** インフラ担当者として、ECS FargateタスクがECRからコンテナイメージをプルできるようVPCネットワークを拡張したい。ISOLATEDサブネット環境でもECSタスクが正常に起動するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECRイメージプルに必要なVPCエンドポイント（com.amazonaws.{region}.ecr.api、Interface型）を作成する
2. THE CDKスタック SHALL ECR Dockerイメージプルに必要なVPCエンドポイント（com.amazonaws.{region}.ecr.dkr、Interface型）を作成する
3. THE CDKスタック SHALL ECRイメージレイヤー取得に必要なVPCエンドポイント（com.amazonaws.{region}.s3、Gateway型）を作成する
4. THE CDKスタック SHALL ECS Fargate用のセキュリティグループを作成し、VPCエンドポイントへのHTTPS（443）アウトバウンドを許可する
5. THE CDKスタック SHALL ECS FargateセキュリティグループからAuroraクラスターへのPostgreSQL（5432）アウトバウンドを許可する
6. THE CDKスタック SHALL 既存のVPCエンドポイントセキュリティグループにECS Fargateセキュリティグループからのインバウンド（443）を追加する
7. THE CDKスタック SHALL 既存のAuroraセキュリティグループにECS Fargateセキュリティグループからのインバウンド（5432）を追加する
8. THE CDKスタック SHALL CloudWatch Logs用VPCエンドポイントをECSタスクのログ出力にも共用する

### 要件 2: ECS Fargate タスク定義（データ投入用）

**ユーザーストーリー:** 検証担当者として、ECS Fargateタスクで10万件のベクトルデータを3つのDBに一括投入したい。大量データ投入のパフォーマンスを計測するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECS Fargateタスク定義をプライベートサブネットで実行可能な構成で作成する
2. THE CDKスタック SHALL ECSタスクのIAMロールにAuroraクラスター（Secrets Manager経由）、OpenSearchコレクション、S3 Vectorsへのアクセス権限を付与する
3. THE CDKスタック SHALL ECSタスクのコンテナイメージをDockerfileからビルドし、ECRにプッシュする構成とする
4. THE CDKスタック SHALL ECSタスクのメモリを4096 MB、vCPUを2に設定する
5. THE CDKスタック SHALL ECSタスクのコンテナにAurora接続情報、OpenSearchエンドポイント、S3 Vectorsバケット名・インデックス名を環境変数として渡す
6. THE CDKスタック SHALL ECSタスクのログをCloudWatch Logsに出力する構成とする
7. THE CDKスタック SHALL ECSタスク定義にremovalPolicy: DESTROYを設定する

### 要件 3: インデックス削除→データ投入→インデックス再作成の戦略

**ユーザーストーリー:** 検証担当者として、大量データ投入時にインデックスを一旦削除してから投入し、投入後にインデックスを再作成したい。インデックス更新のオーバーヘッドを排除し投入パフォーマンスを最大化するためである。

#### 受け入れ基準

1. WHEN 投入ECSタスクがAuroraクラスターへのデータ投入を開始する前に、THE 投入ECSタスク SHALL 既存のHNSWインデックス（embeddings_hnsw_idx）をDROPする
2. WHEN Auroraクラスターへの全データ投入が完了した後、THE 投入ECSタスク SHALL HNSWインデックス（embeddings_hnsw_idx）をCREATE INDEXで再作成する
3. WHEN 投入ECSタスクがOpenSearchコレクションへのデータ投入を開始する前に、THE 投入ECSタスク SHALL 既存のインデックス（embeddings）を削除する
4. WHEN OpenSearchコレクションへの全データ投入が完了した後、THE 投入ECSタスク SHALL OpenSearchインデックス（embeddings）をHNSWマッピング付きで再作成する
5. THE 投入ECSタスク SHALL S3 Vectorsに対してはインデックス削除・再作成を行わず、そのままデータを投入する
6. THE 投入ECSタスク SHALL インデックス削除、データ投入、インデックス再作成の各フェーズの所要時間を個別に計測しログに出力する
7. IF インデックス削除またはインデックス再作成が失敗した場合、THEN THE 投入ECSタスク SHALL エラーをログに記録し該当DBの投入処理を中断する

### 要件 4: 大量ベクトルデータの一括投入

**ユーザーストーリー:** 検証担当者として、10万件の1536次元ベクトルデータを効率的に3つのDBに投入したい。各DBの投入パフォーマンスを公平に比較するためである。

#### 受け入れ基準

1. THE 投入ECSタスク SHALL 1536次元のダミーベクトルを10万件プログラム内で動的に生成する
2. THE 投入ECSタスク SHALL Amazon Bedrock等の外部APIを一切呼び出さずにダミーベクトルを生成する
3. WHEN Auroraクラスターにデータを投入する際、THE 投入ECSタスク SHALL バッチINSERT（1回あたり1000件程度）で効率的に投入する
4. WHEN OpenSearchコレクションにデータを投入する際、THE 投入ECSタスク SHALL Bulk APIで効率的に投入する
5. WHEN S3 Vectorsにデータを投入する際、THE 投入ECSタスク SHALL PutVectors APIのバッチ機能で効率的に投入する
6. THE 投入ECSタスク SHALL 3つのDBへの投入を順次実行し、各DBの投入所要時間を個別に計測する
7. THE 投入ECSタスク SHALL 投入完了後に各DBの投入件数、所要時間、スループット（件/秒）をCloudWatch Logsに構造化ログとして出力する
8. IF データ投入中にエラーが発生した場合、THEN THE 投入ECSタスク SHALL リトライ（最大3回）を実行し、リトライ後も失敗した場合はエラーをログに記録して次のDBの投入に進む


### 要件 5: Lambda検索負荷テスト

**ユーザーストーリー:** 検証担当者として、Lambda関数で3つのDBに対して検索負荷テストを実行したい。10万件のデータが投入された状態での検索レイテンシとスループットを比較するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL 検索テスト用のLambda関数をプライベートサブネットに作成する
2. THE CDKスタック SHALL 検索テストLambdaのIAMロールにAuroraクラスター、OpenSearchコレクション、S3 Vectorsへのアクセス権限を付与する
3. WHEN 検索テストLambdaが実行された際、THE 検索テストLambda SHALL 指定された回数（デフォルト100回）のANNクエリを各DBに対して実行する
4. THE 検索テストLambda SHALL 各クエリのレイテンシ（ミリ秒）を個別に計測する
5. THE 検索テストLambda SHALL 全クエリ完了後に平均レイテンシ、P50、P95、P99レイテンシを算出する
6. THE 検索テストLambda SHALL 検索結果のメトリクスをCloudWatch Logsに構造化ログとして出力する
7. THE 検索テストLambda SHALL イベントパラメータでクエリ回数、top_k値を指定可能とする
8. THE 検索テストLambda SHALL 3つのDBの検索メトリクスを比較可能な形式でレスポンスに含める

### 要件 6: メトリクス収集と結果出力

**ユーザーストーリー:** 検証担当者として、投入と検索のメトリクスを収集し比較表として出力したい。3つのDBのパフォーマンス特性を定量的に比較するためである。

#### 受け入れ基準

1. THE 投入ECSタスク SHALL 各DBについてインデックス削除時間、データ投入時間、インデックス再作成時間、合計時間を記録する
2. THE 投入ECSタスク SHALL 各DBの投入スループット（件/秒）を算出しログに出力する
3. THE 検索テストLambda SHALL 各DBについて平均レイテンシ、P50、P95、P99レイテンシ、スループット（クエリ/秒）を算出する
4. THE 検索テストLambda SHALL 3つのDBのメトリクスを比較表形式（JSON）でレスポンスに含める
5. THE ベンチマークシステム SHALL すべてのメトリクスをCloudWatch Logsに構造化ログ（JSON形式）で出力する

### 要件 7: 環境の安全な破棄

**ユーザーストーリー:** インフラ担当者として、ベンチマーク完了後に `cdk destroy` で追加した全リソースを含めて削除したい。環境維持による無駄なコストをゼロにするためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECSタスク定義、ECSクラスター、ECRリポジトリ等の追加リソースにremovalPolicy: DESTROYを設定する
2. THE CDKスタック SHALL 検索テストLambda関数にremovalPolicy: DESTROYを設定する
3. THE CDKスタック SHALL `cdk destroy` の実行により追加した全リソースが削除される構成とする
4. THE CDKスタック SHALL ECRリポジトリの自動削除（autoDeleteImages: true相当）を設定する

### 要件 8: セキュリティとコスト保護

**ユーザーストーリー:** インフラ担当者として、追加リソースについてもセキュリティベストプラクティスを遵守しつつコストを管理したい。検証環境であっても安全かつコスト管理された状態を維持するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL cdk-nagによるセキュリティチェックに合格する構成を生成する
2. THE CDKスタック SHALL ECSタスクの通信をVPC内のプライベート経路に限定する
3. THE CDKスタック SHALL ECSタスクのIAMロールに必要最小限の権限のみ付与する
4. THE CDKスタック SHALL NAT Gatewayを使用せずVPCエンドポイント経由でECSタスクがAWSサービスにアクセスする構成とする
5. THE 投入ECSタスク SHALL Amazon Bedrock等の外部APIを呼び出さずダミーベクトル生成によりAPI費用を発生させない構成とする
6. THE CDKスタック SHALL 検索テストLambdaのメモリサイズを512 MB以下に設定する
