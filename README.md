# vector-db-benchmark

AWS のベクトルデータベースサービス（Aurora pgvector、OpenSearch Serverless、S3 Vectors）を
実際に構築・動作確認し、知見を蓄積するための技術検証リポジトリ。

## アーキテクチャ

- VPC + プライベートサブネット
- Aurora Serverless v2（pgvector 拡張）
- OpenSearch Serverless（ベクトル検索コレクション）
- Amazon S3 Vectors
- Lambda（Python 3.13）による動作確認関数

## 前提条件

- Node.js 24.x
- Python 3.13
- AWS CLI v2（SSO 設定済み）
- AWS CDK v2（`npm install` で導入）

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
# デフォルトプロファイルを使用
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
