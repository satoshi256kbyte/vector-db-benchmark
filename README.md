# vector-db-benchmark

AWS のベクトルデータベースサービス（Aurora pgvector、OpenSearch Serverless、S3 Vectors）を
実際に構築・動作確認し、知見を蓄積するための技術検証リポジトリ。

## アーキテクチャ

- VPC + プライベートサブネット
- Aurora Serverless v2（pgvector 拡張、0 ACU オートポーズ対応）
- OpenSearch Serverless（ベクトル検索コレクション、冗長スタンバイ無効）
- Amazon S3 Vectors
- Lambda（Python 3.13）による動作確認関数

## 前提条件

- Node.js 24.x
- Python 3.13
- AWS CLI v2（SSO 設定済み）
- AWS CDK v2（`npm install` で導入）
- AWS SAM CLI
- Docker（`sam build --use-container` で使用）

ランタイムバージョンは `.tool-versions`（asdf）で管理。

## セットアップ

```bash
# Node.js 依存のインストール
npm install

# Python 仮想環境のセットアップ
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## AWS 認証

AWS SSO を使用。デプロイ前にログインしてください。

```bash
aws login
```

## デプロイ

### デプロイコマンド

```bash
# 1. Lambda 関数のビルド（Docker コンテナ内で依存ライブラリをビルド）
sam build --use-container

# 2. CDK デプロイ（デフォルトプロファイル）
npx cdk deploy VectorDbBenchmarkStack

# プロファイルを指定する場合
npx cdk deploy VectorDbBenchmarkStack --profile <profile-name>
```

### 差分確認

```bash
npx cdk diff VectorDbBenchmarkStack
```

### 削除

```bash
npx cdk destroy VectorDbBenchmarkStack
```

## 動作確認

デプロイ後、Lambda 関数を実行してベクトルデータベースの動作を確認できます。

```bash
aws lambda invoke \
  --function-name vdbbench-dev-lambda-vector-verify \
  --region ap-northeast-1 \
  /tmp/response.json

cat /tmp/response.json | python -m json.tool
```

Aurora pgvector、OpenSearch Serverless、S3 Vectors それぞれに対して
ダミーベクトルの投入・検索を実行し、結果を JSON で返します。

## コスト最適化

本リポジトリは検証用途のため、以下のコスト最適化設定を適用しています。

| サービス              | 設定                                     | 効果                                                     |
| --------------------- | ---------------------------------------- | -------------------------------------------------------- |
| Aurora Serverless v2  | MinCapacity: 0 ACU（オートポーズ有効）   | 未使用時はコンピュート課金ゼロ（ストレージ課金のみ）     |
| OpenSearch Serverless | standbyReplicas: DISABLED、MaxOCU: 2     | 最小 0.5 OCU × 2 = 1 OCU（インデックス + 検索）で稼働   |

Aurora はコネクションがない状態が続くと自動的にポーズし、接続要求時に自動再開します（コールドスタートあり）。
OpenSearch Serverless はゼロスケールに対応していないため、冗長スタンバイ無効 + OCU 上限制限で最小コストに抑えています。

## テスト

```bash
# CDK テスト（TypeScript）
npm test

# Python テスト
pytest
```

## コード品質

```bash
# TypeScript
npm run lint
npm run format

# Python
ruff check .
ruff format .
mypy .
```

## ディレクトリ構成

```shell
├── bin/                    # CDK アプリケーションエントリポイント
├── lib/
│   ├── constructs/         # CDK Construct（Aurora, OpenSearch, S3 Vectors 等）
│   └── vector-db-benchmark-stack.ts
├── functions/
│   └── vector-verify/      # 動作確認 Lambda 関数（Python）
├── test/                   # CDK テスト（TypeScript / Jest）
├── tests/                  # Python テスト（pytest）
└── docs/                   # ドキュメント・ダイアグラム
```
