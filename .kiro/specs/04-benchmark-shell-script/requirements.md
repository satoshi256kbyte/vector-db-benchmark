# 要件定義書

## はじめに

Spec 03 で構築した ECS Fargate タスク（ecs/bulk-ingest/）を活用し、
3つのベクトルデータベース（Aurora pgvector、OpenSearch Serverless、Amazon S3 Vectors）に対して
ベンチマーク用データ投入を実行・計測するシェルスクリプトを作成する。

本シェルスクリプトはローカル PC 上で実行し、AWS CLI を使用して AWS リソースを操作する。
1回の実行で Aurora → OpenSearch → S3 Vectors の順に3つのDB全てのベンチマークサイクルを
自動的に完了する。

現在の ECS タスク（main.py）は3つのDBを順次処理し、
インデックス削除→データ投入→インデックス再作成を一括で行う方式であるが、
本 Spec ではインデックス操作をシェルスクリプト側に移管し、
ECS タスクの役割をデータ投入のみに簡素化する。

ACU/OCU のスケーリングは CDK 側で固定値として設定済みであり、
シェルスクリプトからの変更は行わない（ACU: 最小0/最大10、OCU: 検索・インデックスともに最大10）。

各DBのベンチマークサイクルは以下の流れで実行する:

- Aurora: 投入前レコード数記録 → インデックス削除（ECS タスク経由） → ECS タスク起動（データ投入） → ECS タスク完了待機 → インデックス作成（ECS タスク経由） → 投入後レコード数記録 → ログ収集 → メトリクス記録
- OpenSearch: 投入前レコード数記録 → ECS タスク起動（データ投入、Bulk API） → ECS タスク完了待機 → 投入後レコード数記録 → ログ収集 → メトリクス記録
- S3 Vectors: 投入前レコード数記録 → ECS タスク起動（データ投入） → ECS タスク完了待機 → 投入後レコード数記録 → ログ収集 → メトリクス記録

レコード数はデフォルト10万件とし、コマンドライン引数で変更可能とする。

## スコープ外

- ベンチマーク結果のダッシュボード化（CloudWatch Dashboard 等）
- 検索テスト Lambda の実行（本 Spec はデータ投入のみ対象）
- CDK スタックの変更
- ECS タスクからのインデックス操作コードの削除（既存コードは残すが、シェルスクリプト経由では使用しない）
- ACU/OCU のシェルスクリプトからの変更（CDK 側で固定値として設定済み）

## 用語集

- **ベンチマークスクリプト**: 本 Spec で作成するシェルスクリプト（scripts/benchmark.sh）。
  ローカル PC 上で実行し、AWS CLI を使用して AWS リソースを操作する
- **投入ECSタスク**: ECS Fargate 上で実行される Python コンテナタスク。
  環境変数 `TARGET_DB` で指定された単一の DB に対してデータ投入のみを実行する。
  インデックス操作は行わない
- **Auroraクラスター**: Aurora Serverless v2 (PostgreSQL + pgvector 拡張) クラスター。
  クラスター識別子: `vdbbench-dev-aurora-pgvector`
- **OpenSearchコレクション**: OpenSearch Serverless ベクトル検索コレクション。
  コレクション名: `vdbbench-dev-oss-vector`。VPC ネットワークポリシーにより
  VPC 内からのみアクセス可能
- **S3ベクトルバケット**: Amazon S3 Vectors ベクトルバケット。
  バケット名: `vdbbench-dev-s3vectors-benchmark`、インデックス名: `embeddings`
- **ECSクラスター**: ECS Fargate クラスター。
  クラスター名: `vdbbench-dev-ecs-benchmark`
- **ACU**: Aurora Capacity Unit。Aurora Serverless v2 のコンピュートキャパシティ単位。
  CDK 側で最小 0 / 最大 10 に固定設定済み
- **OCU**: OpenSearch Capacity Unit。OpenSearch Serverless のコンピュートキャパシティ単位。
  CDK 側で検索・インデックスともに最大 10 に固定設定済み
- **ターゲットDB**: ECS タスクが処理対象とするデータベース。
  `aurora`、`opensearch`、`s3vectors` のいずれか
- **ベンチマーク結果ディレクトリ**: スクリプト実行ごとに作成される
  タイムスタンプ付きディレクトリ（results/YYYYMMDD-HHMMSS/）
- **CloudWatch Logsロググループ**: ECS タスクのログ出力先。
  ロググループ名: `vdbbench-dev-cloudwatch-ecs-bulk-ingest`

## 要件

### 要件 1: ECS タスクの TARGET_DB 環境変数対応（データ投入専用）

**ユーザーストーリー:** 検証担当者として、
ECS タスクを特定のDBのみ処理対象として実行し、
データ投入のみを行わせたい。
インデックス操作はシェルスクリプト側で制御するためである。

#### 受け入れ基準

1. WHEN 環境変数 `TARGET_DB` に `aurora` が設定された場合、
   THE 投入ECSタスク SHALL Aurora pgvector のみを処理対象として
   データ投入のみを実行する（インデックス操作は行わない）
2. WHEN 環境変数 `TARGET_DB` に `opensearch` が設定された場合、
   THE 投入ECSタスク SHALL OpenSearch Serverless のみを処理対象として
   データ投入のみを実行する（インデックス操作は行わない）
3. WHEN 環境変数 `TARGET_DB` に `s3vectors` が設定された場合、
   THE 投入ECSタスク SHALL Amazon S3 Vectors のみを処理対象として
   データ投入のみを実行する
4. WHEN 環境変数 `TARGET_DB` が未設定または `all` の場合、
   THE 投入ECSタスク SHALL 既存の動作どおり
   3つのDB全てを順次処理する（インデックス操作含む、後方互換性維持）
5. IF 環境変数 `TARGET_DB` に無効な値が設定された場合、
   THEN THE 投入ECSタスク SHALL エラーメッセージをログに出力し
   終了コード 1 で終了する
6. WHEN 環境変数 `TARGET_DB` に単一DB名が指定された場合、
   THE 投入ECSタスク SHALL インデックス削除・再作成フェーズをスキップし
   データ投入フェーズのみを実行する

### 要件 2: インデックス操作（ECS タスク経由、Aurora のみ）

**ユーザーストーリー:** 検証担当者として、
シェルスクリプトから Aurora のインデックスの削除と作成を行いたい。
ECS タスクの役割をデータ投入のみに限定し、
インデックス操作のタイミングをシェルスクリプト側で制御するためである。

#### 受け入れ基準

1. WHEN ベンチマークスクリプトが Aurora のデータ投入を開始する前に、
   THE ベンチマークスクリプト SHALL ECS タスクを `TASK_MODE=index_drop` で起動し、
   HNSW インデックス（embeddings_hnsw_idx）の DROP と
   テーブルデータの TRUNCATE を実行する
2. WHEN Aurora のデータ投入が完了した後、
   THE ベンチマークスクリプト SHALL ECS タスクを `TASK_MODE=index_create` で起動し、
   HNSW インデックス（embeddings_hnsw_idx）を再作成する
3. THE ベンチマークスクリプト SHALL S3 Vectors に対しては
   インデックス操作を行わない（S3 Vectors にはユーザー制御可能なインデックスがないため）
4. THE ベンチマークスクリプト SHALL OpenSearch に対しては
   インデックス操作を行わない（既存インデックスに Bulk API で一括投入するのみ）
5. THE ベンチマークスクリプト SHALL インデックス削除・作成の各操作結果をログに記録する
6. IF インデックス操作が失敗した場合、
   THEN THE ベンチマークスクリプト SHALL エラーメッセージを出力し
   該当DBの処理を中断する

### 要件 3: ECS タスク実行と待機

**ユーザーストーリー:** 検証担当者として、
ローカル PC からシェルスクリプトで ECS タスクを起動し完了まで待機したい。
各DBごとにデータ投入の開始時刻と終了時刻を正確に記録するためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL ECS タスクを
   `aws ecs run-task` コマンドで起動する
2. THE ベンチマークスクリプト SHALL ECS タスク起動時に
   環境変数 `RECORD_COUNT` と `TARGET_DB` を
   コンテナオーバーライドで指定する
3. THE ベンチマークスクリプト SHALL ECS タスクの起動前に
   開始時刻（ISO 8601 形式）を記録する
4. THE ベンチマークスクリプト SHALL `aws ecs wait tasks-stopped`
   コマンドで ECS タスクの完了を待機する
5. THE ベンチマークスクリプト SHALL ECS タスク完了後に
   終了時刻（ISO 8601 形式）を記録する
6. THE ベンチマークスクリプト SHALL 開始時刻と終了時刻から
   処理時間（秒）を算出し記録する
7. IF ECS タスクが異常終了した場合、
   THEN THE ベンチマークスクリプト SHALL 終了コードとエラー理由を
   ログに記録し、次のDBの処理に進む

### 要件 4: 投入前後のレコード数記録

**ユーザーストーリー:** 検証担当者として、
データ投入前後のレコード数を記録したい。
投入が正しく完了したことを検証するためである。

#### 受け入れ基準

1. WHEN ベンチマークスクリプトが各DBのデータ投入を開始する前に、
   THE ベンチマークスクリプト SHALL 該当DBの現在のレコード数を取得し記録する
2. WHEN 各DBのデータ投入が完了した後、
   THE ベンチマークスクリプト SHALL 該当DBの投入後レコード数を取得し記録する
3. THE ベンチマークスクリプト SHALL Aurora のレコード数を
   ECS タスク経由（`TASK_MODE=count`）で取得する
   （Aurora はプライベートサブネット内のため直接アクセス不可）
4. THE ベンチマークスクリプト SHALL OpenSearch のレコード数を
   ECS タスク経由（`TASK_MODE=count`）で取得する
   （VPC 制限のため直接アクセス不可）
5. THE ベンチマークスクリプト SHALL S3 Vectors のレコード数を
   ECS タスク経由（`TASK_MODE=count`）で取得する

### 要件 5: CloudWatch Logs からのログ収集

**ユーザーストーリー:** 検証担当者として、
ECS タスクの全ログを保存したい。
ベンチマーク結果の詳細分析と再現性確保のためである。

#### 受け入れ基準

1. WHEN ECS タスクの実行が完了した後、
   THE ベンチマークスクリプト SHALL CloudWatch Logs から
   該当タスクのログストリームを特定し全ログを取得する
2. THE ベンチマークスクリプト SHALL 取得したログを
   ベンチマーク結果ディレクトリに DB 名付きファイル
   （例: aurora-task.log）として保存する
3. THE ベンチマークスクリプト SHALL ログ取得時に
   タスク ID をフィルタ条件として使用し、
   該当タスクのログのみを取得する

### 要件 6: コスト・ACU/OCU メトリクス記録

**ユーザーストーリー:** 検証担当者として、
ベンチマーク実行中の ACU/OCU 現在値とコスト関連情報を記録したい。
各DBのベンチマークコストを把握するためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL Aurora の投入完了後に
   Aurora Serverless v2 の現在の ACU 値を
   CloudWatch メトリクス（ServerlessDatabaseCapacity）から取得し記録する
2. THE ベンチマークスクリプト SHALL OpenSearch の投入完了後に
   OCU の現在の設定値を記録する
3. THE ベンチマークスクリプト SHALL ECS タスクの実行時間と
   タスク定義のリソース設定（vCPU、メモリ）から
   Fargate の概算コストを算出し記録する
4. THE ベンチマークスクリプト SHALL 全DBの処理完了後に
   コストサマリーをベンチマーク結果ディレクトリに保存する

### 要件 7: ベンチマーク結果の構造化出力

**ユーザーストーリー:** 検証担当者として、
ベンチマーク結果を構造化された形式で保存したい。
結果の比較・分析を容易にするためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL 実行ごとに
   タイムスタンプ付きディレクトリ（results/YYYYMMDD-HHMMSS/）を
   作成する
2. THE ベンチマークスクリプト SHALL 各DBの投入結果を
   JSON ファイル（例: aurora-result.json）として保存する
3. THE ベンチマークスクリプト SHALL 全DBの結果を統合した
   サマリー JSON ファイル（summary.json）を生成する
4. THE ベンチマークスクリプト SHALL サマリーに
   レコード数、各DBの処理時間、スループット、
   投入前後のレコード数、インデックス状態を含める
5. THE ベンチマークスクリプト SHALL 実行完了時に
   サマリーの内容をコンソールに表示する

### 要件 8: コマンドライン引数とパラメータ化

**ユーザーストーリー:** 検証担当者として、
レコード数やリソース名をコマンドライン引数で指定可能にしたい。
異なる条件でのベンチマーク実行を容易にするためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL レコード数を
   コマンドライン引数 `--record-count`（デフォルト 100000）で
   指定可能とする
2. THE ベンチマークスクリプト SHALL Aurora クラスター識別子を
   コマンドライン引数 `--aurora-cluster`
   （デフォルト `vdbbench-dev-aurora-pgvector`）で指定可能とする
3. THE ベンチマークスクリプト SHALL OpenSearch コレクション名を
   コマンドライン引数 `--opensearch-collection`
   （デフォルト `vdbbench-dev-oss-vector`）で指定可能とする
4. THE ベンチマークスクリプト SHALL S3 Vectors バケット名を
   コマンドライン引数 `--s3vectors-bucket`
   （デフォルト `vdbbench-dev-s3vectors-benchmark`）で指定可能とする
5. THE ベンチマークスクリプト SHALL ECS クラスター名を
   コマンドライン引数 `--ecs-cluster`
   （デフォルト `vdbbench-dev-ecs-benchmark`）で指定可能とする
6. THE ベンチマークスクリプト SHALL AWS リージョンを
   コマンドライン引数 `--region`（デフォルト `ap-northeast-1`）で
   指定可能とする
7. THE ベンチマークスクリプト SHALL `--help` オプションで
   利用可能な全引数とデフォルト値を表示する

### 要件 9: エラーハンドリングと堅牢性

**ユーザーストーリー:** 検証担当者として、
スクリプトがエラー発生時にも適切に処理を継続することを保証したい。
環境の不整合を防ぐためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL `set -euo pipefail` を設定し
   未定義変数の使用やパイプラインエラーを検出する
2. THE ベンチマークスクリプト SHALL trap を使用して
   スクリプトの異常終了時にクリーンアップ処理を実行する
3. IF 1つのDBの処理でエラーが発生した場合、
   THEN THE ベンチマークスクリプト SHALL エラーを記録し
   次のDBの処理に進む
4. THE ベンチマークスクリプト SHALL 各 AWS CLI コマンドの
   実行結果を確認し、失敗時にはエラーメッセージを出力する
5. THE ベンチマークスクリプト SHALL 実行開始時に
   必要な前提条件（aws CLI、jq、bc コマンドの存在、
   AWS 認証情報の有効性）を確認する

### 要件 10: 処理順序の制御

**ユーザーストーリー:** 検証担当者として、
Aurora → OpenSearch → S3 Vectors の順序で
各DBのベンチマークサイクルを1回の実行で自動的に完了したい。
一貫した順序で結果を比較するためである。

#### 受け入れ基準

1. THE ベンチマークスクリプト SHALL Aurora pgvector、
   OpenSearch Serverless、Amazon S3 Vectors の順序で
   各DBのベンチマークサイクルを実行する
2. THE ベンチマークスクリプト SHALL 各DBのベンチマークサイクルで
   以下の手順を順次実行する:
   - Aurora: 投入前レコード数記録 → インデックス削除（ECS タスク経由） →
     開始時刻記録 → ECS タスク起動（データ投入のみ）→
     ECS タスク完了待機 → 終了時刻記録 →
     インデックス作成（ECS タスク経由）→ 投入後レコード数記録 →
     ログ収集 → メトリクス記録
   - OpenSearch: 投入前レコード数記録 →
     開始時刻記録 → ECS タスク起動（データ投入、Bulk API）→
     ECS タスク完了待機 → 終了時刻記録 →
     投入後レコード数記録 → ログ収集 → メトリクス記録
   - S3 Vectors: 投入前レコード数記録 →
     開始時刻記録 → ECS タスク起動（データ投入）→
     ECS タスク完了待機 → 終了時刻記録 →
     投入後レコード数記録 → ログ収集 → メトリクス記録
3. THE ベンチマークスクリプト SHALL 各DBの処理間に
   区切りログを出力し、進捗を明確にする
4. THE ベンチマークスクリプト SHALL 1回の実行で
   3つのDB全てのベンチマークサイクルを自動的に完了する
