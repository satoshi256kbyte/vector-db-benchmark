# 要件定義書

## はじめに

データ投入が完了した3つのベクトルDB（Aurora pgvector、OpenSearch Serverless、Amazon S3 Vectors）に対して、
検索処理のベンチマークテストを実行するシェルスクリプトを作成する。

既にデプロイ済みの検索テスト Lambda 関数（`vdbbench-dev-lambda-search-test`）を
AWS CLI 経由で invoke し、各DBに対して100回ずつベクトル検索を実行して
処理時間の統計値（平均、P50、P95、P99、最小、最大）とスループット（QPS）を計測する。

本シェルスクリプトはローカル PC 上で実行し、既存の `scripts/benchmark.sh` と同様のパターン
（ログユーティリティ、引数パース、結果 JSON 生成、コンソールサマリー表示）を踏襲する。

検索テスト Lambda は VPC 内 ISOLATED サブネットで動作し、
VPC エンドポイント経由で各 AWS サービスにアクセスする。
Lambda 内部で3つのDBに対して順次検索を実行し、
各DBのレイテンシ統計・スループット・比較表を含むレスポンスを返却する。

## スコープ外

- 新規 Lambda 関数の作成（既存の search-test Lambda を使用）
- CDK スタックの変更
- データ投入処理（Spec 04 の benchmark.sh が担当）
- CloudWatch Dashboard の作成
- 検索テスト Lambda のコード変更

## 用語集

- **検索ベンチマークスクリプト**: 本 Spec で作成するシェルスクリプト（scripts/search-benchmark.sh）。
  ローカル PC 上で実行し、AWS CLI で検索テスト Lambda を invoke する
- **検索テストLambda**: デプロイ済みの Lambda 関数（vdbbench-dev-lambda-search-test）。
  3つのベクトルDBに対してベクトル検索を実行し、レイテンシ統計とスループットを返却する
- **Auroraクラスター**: Aurora Serverless v2 (PostgreSQL + pgvector 拡張) クラスター。
  クラスター識別子: `vdbbench-dev-aurora-pgvector`
- **OpenSearchコレクション**: OpenSearch Serverless ベクトル検索コレクション。
  コレクション名: `vdbbench-dev-oss-vector`
- **S3ベクトルバケット**: Amazon S3 Vectors ベクトルバケット。
  バケット名: `vdbbench-dev-s3vectors-benchmark`、インデックス名: `embeddings`
- **レイテンシ統計**: 検索クエリの処理時間統計。
  平均（avg_ms）、P50、P95、P99、最小（min_ms）、最大（max_ms）をミリ秒単位で表す
- **スループット**: 単位時間あたりのクエリ処理数。QPS（Queries Per Second）で表す
- **検索回数**: 各DBに対して実行するベクトル検索クエリの回数。デフォルト 100 回
- **top_k**: 各検索クエリで返却する近傍ベクトルの件数。デフォルト 10 件
- **投入済みレコード数**: ベクトルDBに投入済みのレコード数。
  クエリベクトル生成時のサンプリング範囲として使用する。デフォルト 100000
- **ベンチマーク結果ディレクトリ**: スクリプト実行ごとに作成される
  タイムスタンプ付きディレクトリ（results/YYYYMMDD-HHMMSS/）

## 要件

### 要件 1: Lambda 関数の invoke と結果取得

**ユーザーストーリー:** 検証担当者として、
ローカル PC からシェルスクリプトで検索テスト Lambda を invoke し、
3つのDBの検索ベンチマーク結果を取得したい。
各DBの検索性能を定量的に比較するためである。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL 検索テストLambda を
   `aws lambda invoke` コマンドで同期的に invoke する
2. THE 検索ベンチマークスクリプト SHALL invoke 時のペイロードに
   `search_count`、`top_k`、`record_count` パラメータを JSON 形式で指定する
3. THE 検索ベンチマークスクリプト SHALL Lambda のレスポンスから
   各DB（aurora、opensearch、s3vectors）のレイテンシ統計、スループット、
   成否を抽出する
4. IF Lambda の invoke が失敗した場合（HTTP ステータスコードが 200 以外）、
   THEN THE 検索ベンチマークスクリプト SHALL エラーメッセージをログに出力し
   処理を中断する
5. IF Lambda のレスポンスに FunctionError が含まれる場合、
   THEN THE 検索ベンチマークスクリプト SHALL Lambda 実行エラーの詳細を
   ログに出力し処理を中断する

### 要件 2: 検索結果の構造化出力

**ユーザーストーリー:** 検証担当者として、
検索ベンチマーク結果を構造化された形式で保存したい。
結果の比較・分析を容易にするためである。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL 実行ごとに
   タイムスタンプ付きディレクトリ（results/YYYYMMDD-HHMMSS/）を作成する
2. THE 検索ベンチマークスクリプト SHALL 各DBの検索結果を
   個別の JSON ファイル（aurora-search.json、opensearch-search.json、
   s3vectors-search.json）として保存する
3. THE 検索ベンチマークスクリプト SHALL 各DBの検索結果 JSON に
   データベース名、レイテンシ統計（avg_ms、p50_ms、p95_ms、p99_ms、min_ms、max_ms）、
   スループット（QPS）、検索回数、top_k、成否を含める
4. THE 検索ベンチマークスクリプト SHALL 全DBの結果を統合した
   サマリー JSON ファイル（search-summary.json）を生成する
5. THE 検索ベンチマークスクリプト SHALL サマリー JSON に
   ベンチマーク ID、リージョン、検索パラメータ（search_count、top_k、record_count）、
   各DBの検索結果、比較表データ、全体の処理時間を含める

### 要件 3: コンソールサマリー表示

**ユーザーストーリー:** 検証担当者として、
検索ベンチマーク完了時に結果のサマリーをコンソールで確認したい。
結果ファイルを開かずに概要を把握するためである。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL 実行完了時に
   各DBのレイテンシ統計（avg_ms、p50_ms、p95_ms、p99_ms）を
   コンソールに表形式で表示する
2. THE 検索ベンチマークスクリプト SHALL 各DBのスループット（QPS）を
   コンソールに表示する
3. THE 検索ベンチマークスクリプト SHALL 各DBの検索成否を
   コンソールに表示する
4. THE 検索ベンチマークスクリプト SHALL 結果ファイルの保存先パスを
   コンソールに表示する

### 要件 4: コマンドライン引数とパラメータ化

**ユーザーストーリー:** 検証担当者として、
検索回数や top_k をコマンドライン引数で指定可能にしたい。
異なる条件での検索ベンチマーク実行を容易にするためである。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL 検索回数を
   コマンドライン引数 `--search-count`（デフォルト 100）で指定可能とする
2. THE 検索ベンチマークスクリプト SHALL 近傍返却件数を
   コマンドライン引数 `--top-k`（デフォルト 10）で指定可能とする
3. THE 検索ベンチマークスクリプト SHALL 投入済みレコード数を
   コマンドライン引数 `--record-count`（デフォルト 100000）で指定可能とする
4. THE 検索ベンチマークスクリプト SHALL Lambda 関数名を
   コマンドライン引数 `--function-name`
   （デフォルト `vdbbench-dev-lambda-search-test`）で指定可能とする
5. THE 検索ベンチマークスクリプト SHALL AWS リージョンを
   コマンドライン引数 `--region`（デフォルト `ap-northeast-1`）で指定可能とする
6. THE 検索ベンチマークスクリプト SHALL `--help` オプションで
   利用可能な全引数とデフォルト値を表示する

### 要件 5: エラーハンドリングと堅牢性

**ユーザーストーリー:** 検証担当者として、
スクリプトがエラー発生時にも適切に処理し、
原因を特定できる情報を提供することを保証したい。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL `set -euo pipefail` を設定し
   未定義変数の使用やパイプラインエラーを検出する
2. THE 検索ベンチマークスクリプト SHALL 実行開始時に
   必要な前提条件（aws CLI、jq コマンドの存在、AWS 認証情報の有効性）を確認する
3. IF 前提条件チェックが失敗した場合、
   THEN THE 検索ベンチマークスクリプト SHALL 不足している前提条件を
   エラーメッセージで明示し、終了コード 1 で終了する
4. THE 検索ベンチマークスクリプト SHALL Lambda の invoke 開始前に
   Lambda 関数の存在を `aws lambda get-function` で確認する
5. IF Lambda 関数が存在しない場合、
   THEN THE 検索ベンチマークスクリプト SHALL 関数名を含むエラーメッセージを出力し
   終了コード 1 で終了する

### 要件 6: ログ出力

**ユーザーストーリー:** 検証担当者として、
スクリプトの実行状況をリアルタイムで把握したい。
処理の進捗確認とトラブルシューティングのためである。

#### 受け入れ基準

1. THE 検索ベンチマークスクリプト SHALL 既存の benchmark.sh と同様の
   ログユーティリティ（log_info、log_error、log_separator）を使用する
2. THE 検索ベンチマークスクリプト SHALL Lambda invoke の開始時に
   検索パラメータ（search_count、top_k、record_count）をログに出力する
3. THE 検索ベンチマークスクリプト SHALL Lambda invoke の完了時に
   Lambda の実行時間をログに出力する
4. THE 検索ベンチマークスクリプト SHALL 各処理ステップの開始・完了を
   ログに出力し、進捗を明確にする
