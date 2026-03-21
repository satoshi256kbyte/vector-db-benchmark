# 技術スタック

## IaC

### AWS CDK (TypeScript)

- AWS CDK v2
- TypeScript で記述
- cdk-nag によるセキュリティチェック

### パッケージマネージャー（CDK）

- npm（CDK プロジェクト用）

## アプリケーション / バッチ

### 言語

- Python 3.13
  - 型ヒント（type hints）を積極的に使用
  - dataclasses / Pydantic でデータモデル定義

### 主要ライブラリ

- boto3 / botocore: AWS SDK for Python
- pytest: テストフレームワーク
- ruff: リンター・フォーマッター
- mypy: 静的型チェック

### Lambda

- Python ランタイム
- Powertools for AWS Lambda (Python): ロギング・トレーシング・メトリクス
- ハンドラーは簡潔に、ビジネスロジックは別モジュールに分離
- 環境変数で設定を管理

## AWS サービス（検証対象例）

- Amazon DynamoDB
- AWS Lambda
- Amazon API Gateway
- Amazon S3
- Amazon EventBridge
- Amazon Bedrock
- Amazon Cognito
- Amazon CloudFront
- Amazon SQS / SNS
- AWS Step Functions

## 開発環境

### ランタイム管理

- asdf（.tool-versions で Node.js / Python バージョンを管理）

### コード品質（Python）

- ruff: リント + フォーマット
- mypy: 型チェック
- pytest: テスト

### コード品質（CDK / TypeScript）

- ESLint
- Prettier

### Git

- GitHub
- GitHub Actions for CI/CD

## CI/CD

### パイプライン

- GitHub Actions
  - Lint / Type Check
  - テスト実行
  - CDK diff / deploy

### IaC

- AWS CDK (TypeScript)
  - インフラのコード管理
  - スタック管理
- cdk-nag
  - セキュリティベストプラクティスのチェック
