# タスクリスト

## タスク 1: シェルスクリプトの基本構造とログユーティリティ

- [x] 1.1 `scripts/search-benchmark.sh` を作成し、shebang（`#!/usr/bin/env bash`）と `set -euo pipefail` を設定する
- [x] 1.2 ログユーティリティ関数（`log_info`、`log_error`、`log_separator`）を実装する
- [x] 1.3 `usage()` 関数を実装し、全引数とデフォルト値を表示する
- [x] 1.4 スクリプトに実行権限を付与する（`chmod +x`）

**要件マッピング:** 要件 6（ログ出力）、要件 4-AC6（--help）

## タスク 2: 引数パースと前提条件チェック

- [x] 2.1 `parse_args()` 関数を実装する（`--search-count`/`-s`、`--top-k`/`-k`、`--record-count`/`-r`、`--function-name`/`-f`、`--region`、`--help`/`-h`）
- [x] 2.2 デフォルト値を設定する（search_count=100、top_k=10、record_count=100000、function_name=vdbbench-dev-lambda-search-test、region=ap-northeast-1）
- [x] 2.3 `check_prerequisites()` 関数を実装する（aws CLI、jq コマンドの存在確認、AWS 認証情報の有効性確認）
- [x] 2.4 Lambda 関数の存在確認（`aws lambda get-function`）を実装する
- [x] 2.5 bats テスト `tests/scripts/test_search_benchmark.bats` を作成し、引数パースと前提条件チェックのテストを実装する

**要件マッピング:** 要件 4（コマンドライン引数）、要件 5（エラーハンドリング）

## タスク 3: Lambda invoke と結果取得

- [x] 3.1 `invoke_search_lambda()` 関数を実装する（`aws lambda invoke` で同期 invoke、ペイロードに search_count/top_k/record_count を指定）
- [x] 3.2 Lambda invoke のエラーハンドリングを実装する（invoke 失敗、FunctionError、statusCode ≠ 200）
- [x] 3.3 Lambda レスポンスの body をパースし、各DB（aurora、opensearch、s3vectors）の結果を抽出する
- [x] 3.4 Lambda invoke の開始・完了ログ出力を実装する

**要件マッピング:** 要件 1（Lambda invoke と結果取得）、要件 6-AC2/AC3（ログ）

## タスク 4: 結果 JSON 保存とサマリー生成

- [x] 4.1 タイムスタンプ付き結果ディレクトリ（`results/YYYYMMDD-HHMMSS/`）の作成を実装する
- [x] 4.2 `save_db_result_json()` 関数を実装する（aurora-search.json、opensearch-search.json、s3vectors-search.json を保存）
- [x] 4.3 `generate_search_summary()` 関数を実装する（search-summary.json を生成。benchmark_id、region、search_params、results、comparison、total_duration_seconds、completed_at を含む）
- [x] 4.4 Hypothesis テスト `tests/scripts/test_search_result_json.py` を作成し、個別DB結果 JSON とサマリー JSON のスキーマ検証を実装する

**要件マッピング:** 要件 2（検索結果の構造化出力）

## タスク 5: コンソールサマリー表示と main 関数

- [x] 5.1 `print_search_summary()` 関数を実装する（各DBのレイテンシ統計・QPS・成否を表形式で表示）
- [x] 5.2 結果ファイルの保存先パスをコンソールに表示する
- [x] 5.3 `main()` 関数を実装し、全処理フローを統合する（引数パース → 前提条件チェック → Lambda invoke → 結果保存 → サマリー表示）
- [x] 5.4 bats テストにコンソール出力のテストを追加する
- [x] 5.5 全テスト（bats + pytest）を実行し、全 pass を確認する

**要件マッピング:** 要件 3（コンソールサマリー表示）、要件 6-AC4（進捗ログ）
