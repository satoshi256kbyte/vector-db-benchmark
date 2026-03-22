# 要件定義書

## はじめに

Spec 01（ベクトルDB ベンチマーク基盤）で構築した3つのベクトルデータベース
（Aurora Serverless v2 pgvector、OpenSearch Serverless、Amazon S3 Vectors）に対して、
ECS Fargate タスクで大量ベクトルデータを一括投入し、
Lambda 関数で検索負荷テストを実施するベンチマーク実行基盤を構築する。

データ投入時のパフォーマンス最適化として、
Aurora pgvector および OpenSearch Serverless では
インデックスを一旦削除してからデータを投入し、
投入完了後にインデックスを再作成する戦略を採用する。
S3 Vectors はインデックスアルゴリズムがユーザー指定不可
（内部自動最適化）であるため、インデックス操作なしでそのまま投入する。

レコード数（データ投入件数）と検索回数（Lambda検索テスト回数）は
パラメータで指定可能とし、テスト時は少量、
本番ベンチマーク時は大量（10万件等）に切り替え可能とする。

現在のVPCはISOLATEDサブネットのみ（NAT Gateway なし）であるため、
ECS Fargate タスクがECRイメージをプルするには
VPCエンドポイント（ECR API、ECR Docker、S3 Gateway）の追加が必要となる。

## スコープ外

- ベンチマーク結果のダッシュボード化（CloudWatch Dashboard等）
- 複数回ベンチマーク実行の自動化（Step Functions等）
- ベクトルデータの永続保存（検証完了後は環境ごと破棄）

## 用語集

- **ベンチマークシステム**: 本Specにおける全体システム
  （CDKスタック、ECSタスク、検索テストLambda、ターゲットDB含む）
- **CDKスタック**: AWS CDK v2 (TypeScript) で定義される
  インフラストラクチャ一式（VectorDbBenchmarkStack）
- **投入ECSタスク**: ECS Fargate上で実行されるPythonコンテナタスク。
  パラメータで指定された件数のベクトルデータを3つのDBに一括投入する
- **検索テストLambda**: 検索負荷テストを実行するLambda関数。
  各DBに対してANNクエリを実行しレイテンシを計測する
- **Auroraクラスター**: Spec 01で構築済みの
  Aurora Serverless v2 (PostgreSQL + pgvector拡張) クラスター
- **OpenSearchコレクション**: Spec 01で構築済みの
  OpenSearch Serverless ベクトル検索コレクション
- **S3ベクトルバケット**: Spec 01で構築済みの
  Amazon S3 Vectorsベクトルバケット
- **HNSWインデックス**: Hierarchical Navigable Small World
  アルゴリズムによるベクトル検索インデックス
- **バッチサイズ**: 1回のAPI呼び出しで投入するベクトル件数
- **ANNクエリ**: 近似最近傍探索
  （Approximate Nearest Neighbor）によるベクトル検索クエリ
- **投入メトリクス**: データ投入に関する計測値
  （所要時間、スループット等）
- **検索メトリクス**: 検索テストに関する計測値
  （レイテンシ、スループット等）
- **レコード数パラメータ**: ECSタスクに渡すデータ投入件数の指定値
  （デフォルト100000件）
- **検索回数パラメータ**: 検索テストLambdaに渡す
  クエリ実行回数の指定値（デフォルト100回）

## 要件

### 要件 1: VPCネットワーク拡張（ECS Fargate対応）

**ユーザーストーリー:** インフラ担当者として、
ECS FargateタスクがECRからコンテナイメージをプルできるよう
VPCネットワークを拡張したい。
ISOLATEDサブネット環境でもECSタスクが正常に起動するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECRイメージプルに必要なVPCエンドポイント
   （com.amazonaws.{region}.ecr.api、Interface型）を作成する
2. THE CDKスタック SHALL ECR Dockerイメージプルに必要なVPCエンドポイント
   （com.amazonaws.{region}.ecr.dkr、Interface型）を作成する
3. THE CDKスタック SHALL ECRイメージレイヤー取得に必要なVPCエンドポイント
   （com.amazonaws.{region}.s3、Gateway型）を作成する
4. THE CDKスタック SHALL ECS Fargate用のセキュリティグループを作成し、
   VPCエンドポイントへのHTTPS（443）アウトバウンドを許可する
5. THE CDKスタック SHALL ECS Fargateセキュリティグループから
   Auroraクラスターへの PostgreSQL（5432）アウトバウンドを許可する
6. THE CDKスタック SHALL 既存のVPCエンドポイントセキュリティグループに
   ECS Fargateセキュリティグループからのインバウンド（443）を追加する
7. THE CDKスタック SHALL 既存のAuroraセキュリティグループに
   ECS Fargateセキュリティグループからのインバウンド（5432）を追加する
8. THE CDKスタック SHALL CloudWatch Logs用VPCエンドポイントを
   ECSタスクのログ出力にも共用する

### 要件 2: ECS Fargate タスク定義（データ投入用）

**ユーザーストーリー:** 検証担当者として、
ECS Fargateタスクでベクトルデータを3つのDBに一括投入したい。
大量データ投入のパフォーマンスを計測するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECS Fargateタスク定義を
   プライベートサブネットで実行可能な構成で作成する
2. THE CDKスタック SHALL ECSタスクのIAMロールに
   Auroraクラスター（Secrets Manager経由）、
   OpenSearchコレクション、S3 Vectorsへのアクセス権限を付与する
3. THE CDKスタック SHALL ECSタスクのコンテナイメージを
   Dockerfileからビルドし、ECRにプッシュする構成とする
4. THE CDKスタック SHALL ECSタスクのメモリを4096 MB、
   vCPUを2に設定する
5. THE CDKスタック SHALL ECSタスクのコンテナに
   Aurora接続情報、OpenSearchエンドポイント、
   S3 Vectorsバケット名・インデックス名を環境変数として渡す
6. THE CDKスタック SHALL ECSタスクのログを
   CloudWatch Logsに出力する構成とする
7. THE CDKスタック SHALL ECSタスク定義に
   removalPolicy: DESTROYを設定する

### 要件 3: インデックス戦略（削除→投入→再作成）

**ユーザーストーリー:** 検証担当者として、
大量データ投入時にインデックスを一旦削除してから投入し、
投入後にインデックスを再作成したい。
インデックス更新のオーバーヘッドを排除し
投入パフォーマンスを最大化するためである。

#### 受け入れ基準

1. WHEN 投入ECSタスクがAuroraクラスターへのデータ投入を開始する前に、
   THE 投入ECSタスク SHALL 既存のHNSWインデックス
   （embeddings_hnsw_idx）をDROPする
2. WHEN Auroraクラスターへの全データ投入が完了した後、
   THE 投入ECSタスク SHALL HNSWインデックス
   （embeddings_hnsw_idx）をCREATE INDEXで再作成する
3. WHEN 投入ECSタスクがOpenSearchコレクションへの
   データ投入を開始する前に、
   THE 投入ECSタスク SHALL 既存のインデックス
   （embeddings）を削除する
4. WHEN OpenSearchコレクションへの全データ投入が完了した後、
   THE 投入ECSタスク SHALL OpenSearchインデックス
   （embeddings）をHNSWマッピング付きで再作成する
5. THE 投入ECSタスク SHALL S3 Vectorsに対しては
   インデックス削除・再作成を行わず、そのままデータを投入する
6. THE 投入ECSタスク SHALL インデックス削除、データ投入、
   インデックス再作成の各フェーズの所要時間を
   個別に計測しログに出力する
7. IF インデックス削除またはインデックス再作成が失敗した場合、
   THEN THE 投入ECSタスク SHALL エラーをログに記録し
   該当DBの投入処理を中断する

### 要件 4: 大量ベクトルデータの一括投入

**ユーザーストーリー:** 検証担当者として、
パラメータで指定された件数の1536次元ベクトルデータを
効率的に3つのDBに投入したい。
各DBの投入パフォーマンスを公平に比較するためである。

#### 受け入れ基準

1. THE 投入ECSタスク SHALL 1536次元のダミーベクトルを
   レコード数パラメータで指定された件数
   （デフォルト100000件）プログラム内で動的に生成する
2. THE 投入ECSタスク SHALL Amazon Bedrock等の外部APIを
   一切呼び出さずにダミーベクトルを生成する
3. THE 投入ECSタスク SHALL レコード数パラメータを
   環境変数またはコマンドライン引数で受け取る
4. WHEN Auroraクラスターにデータを投入する際、
   THE 投入ECSタスク SHALL バッチINSERT
   （1回あたり1000件程度）で効率的に投入する
5. WHEN OpenSearchコレクションにデータを投入する際、
   THE 投入ECSタスク SHALL Bulk APIで効率的に投入する
6. WHEN S3 Vectorsにデータを投入する際、
   THE 投入ECSタスク SHALL PutVectors APIの
   バッチ機能で効率的に投入する
7. THE 投入ECSタスク SHALL 3つのDBへの投入を順次実行し、
   各DBの投入所要時間を個別に計測する
8. THE 投入ECSタスク SHALL 投入完了後に各DBの投入件数、
   所要時間、スループット（件/秒）を
   CloudWatch Logsに構造化ログとして出力する
9. IF データ投入中にエラーが発生した場合、
   THEN THE 投入ECSタスク SHALL リトライ（最大3回）を実行し、
   リトライ後も失敗した場合はエラーをログに記録して
   次のDBの投入に進む

### 要件 5: Lambda検索負荷テスト

**ユーザーストーリー:** 検証担当者として、
Lambda関数で3つのDBに対して検索負荷テストを実行したい。
大量データが投入された状態での検索レイテンシと
スループットを比較するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL 検索テスト用のLambda関数を
   プライベートサブネットに作成する
2. THE CDKスタック SHALL 検索テストLambdaのIAMロールに
   Auroraクラスター、OpenSearchコレクション、
   S3 Vectorsへのアクセス権限を付与する
3. WHEN 検索テストLambdaが実行された際、
   THE 検索テストLambda SHALL 検索回数パラメータで
   指定された回数（デフォルト100回）のANNクエリを
   各DBに対して実行する
4. THE 検索テストLambda SHALL 各クエリのレイテンシ
   （ミリ秒）を個別に計測する
5. THE 検索テストLambda SHALL 全クエリ完了後に
   平均レイテンシ、P50、P95、P99レイテンシを算出する
6. THE 検索テストLambda SHALL 検索結果のメトリクスを
   CloudWatch Logsに構造化ログとして出力する
7. THE 検索テストLambda SHALL イベントパラメータで
   クエリ回数（search_count）、top_k値を指定可能とする
8. THE 検索テストLambda SHALL 3つのDBの検索メトリクスを
   比較可能な形式でレスポンスに含める

### 要件 6: メトリクス収集と結果出力

**ユーザーストーリー:** 検証担当者として、
投入と検索のメトリクスを収集し比較表として出力したい。
3つのDBのパフォーマンス特性を定量的に比較するためである。

#### 受け入れ基準

1. THE 投入ECSタスク SHALL 各DBについて
   インデックス削除時間、データ投入時間、
   インデックス再作成時間、合計時間を記録する
2. THE 投入ECSタスク SHALL 各DBの投入スループット
   （件/秒）を算出しログに出力する
3. THE 検索テストLambda SHALL 各DBについて
   平均レイテンシ、P50、P95、P99レイテンシ、
   スループット（クエリ/秒）を算出する
4. THE 検索テストLambda SHALL 3つのDBのメトリクスを
   比較表形式（JSON）でレスポンスに含める
5. THE ベンチマークシステム SHALL すべてのメトリクスを
   CloudWatch Logsに構造化ログ（JSON形式）で出力する

### 要件 7: パラメータ化

**ユーザーストーリー:** 検証担当者として、
レコード数と検索回数をパラメータで指定可能にしたい。
テスト時は少量（100件等）で動作確認し、
本番ベンチマーク時は大量（10万件等）に
切り替えられるようにするためである。

#### 受け入れ基準

1. THE 投入ECSタスク SHALL レコード数パラメータ
   （RECORD_COUNT）を環境変数で受け取り、
   指定された件数のベクトルデータを投入する
2. THE 投入ECSタスク SHALL レコード数パラメータが
   未指定の場合、デフォルト値100000件で動作する
3. THE 検索テストLambda SHALL 検索回数パラメータ
   （search_count）をイベントペイロードで受け取り、
   指定された回数のANNクエリを実行する
4. THE 検索テストLambda SHALL 検索回数パラメータが
   未指定の場合、デフォルト値100回で動作する
5. THE 検索テストLambda SHALL top_kパラメータを
   イベントペイロードで受け取り、
   指定された件数の近傍を返却する
6. THE 検索テストLambda SHALL top_kパラメータが
   未指定の場合、デフォルト値10で動作する

### 要件 8: 環境の安全な破棄

**ユーザーストーリー:** インフラ担当者として、
ベンチマーク完了後に `cdk destroy` で
追加した全リソースを含めて削除したい。
環境維持による無駄なコストをゼロにするためである。

#### 受け入れ基準

1. THE CDKスタック SHALL ECSタスク定義、ECSクラスター、
   ECRリポジトリ等の追加リソースに
   removalPolicy: DESTROYを設定する
2. THE CDKスタック SHALL 検索テストLambda関数に
   removalPolicy: DESTROYを設定する
3. THE CDKスタック SHALL `cdk destroy` の実行により
   追加した全リソースが削除される構成とする
4. THE CDKスタック SHALL ECRリポジトリの自動削除
   （autoDeleteImages: true相当）を設定する

### 要件 9: セキュリティとコスト保護

**ユーザーストーリー:** インフラ担当者として、
追加リソースについてもセキュリティベストプラクティスを
遵守しつつコストを管理したい。
検証環境であっても安全かつコスト管理された状態を
維持するためである。

#### 受け入れ基準

1. THE CDKスタック SHALL cdk-nagによる
   セキュリティチェックに合格する構成を生成する
2. THE CDKスタック SHALL ECSタスクの通信を
   VPC内のプライベート経路に限定する
3. THE CDKスタック SHALL ECSタスクのIAMロールに
   必要最小限の権限のみ付与する
4. THE CDKスタック SHALL NAT Gatewayを使用せず
   VPCエンドポイント経由でECSタスクが
   AWSサービスにアクセスする構成とする
5. THE 投入ECSタスク SHALL Amazon Bedrock等の
   外部APIを呼び出さずダミーベクトル生成により
   API費用を発生させない構成とする
6. THE CDKスタック SHALL 検索テストLambdaの
   メモリサイズを512 MB以下に設定する
