# 実装ガイド

## ブランチ運用

GitHub Flow を採用

- `main`: 本番環境
- `develop`: 開発環境
- `feature/*`: 機能開発
- `fix/*`: バグ修正

### Kiro（AI アシスタント）の Git 操作ルール

**禁止事項:**

- ブランチの切り替え（`git checkout`、`git switch`）は禁止
- `main` ブランチへの直接プッシュは禁止
- `main` ブランチへのマージは禁止

**許可される操作:**

- 現在のブランチへのコミット
- 現在のブランチへのプッシュ
- ファイルの作成・編集・削除

**ワークフロー:**

1. ユーザーが適切なブランチに切り替える
2. Kiro がそのブランチで作業（コミット・プッシュ）
3. `main` へのマージはユーザーが Pull Request 経由で実施

参考: [GitHub Flow](https://docs.github.com/ja/get-started/using-github/github-flow)

## コミットメッセージ

Conventional Commits に準拠

```text
<type>: <subject>

<body>
```

### Type

- `feat`: 新機能
- `fix`: バグ修正
- `docs`: ドキュメント
- `style`: フォーマット
- `refactor`: リファクタリング
- `test`: テスト
- `chore`: その他

参考: [Conventional Commits](https://www.conventionalcommits.org/ja/)

## Python コーディング規約

### 基本方針

- 型ヒントを必ず付与する
- `Any` は使用しない
- docstring は Google スタイル
- f-string を優先（`format()` や `%` は使わない）

### プロジェクト構成（Lambda 関数）

```text
functions/
  <function-name>/
    handler.py          # Lambda ハンドラー（エントリポイント）
    logic.py            # ビジネスロジック
    models.py           # データモデル（dataclass / Pydantic）
    requirements.txt    # 依存ライブラリ
    tests/
      test_handler.py
      test_logic.py
```

### テスト（pytest）

- テストファイルは `tests/` ディレクトリに配置
- ファイル名は `test_` プレフィックス
- フィクスチャを活用してセットアップを共通化
- AWS サービスのモックには moto または pytest-mock を使用

```python
import pytest
from unittest.mock import MagicMock
from handler import lambda_handler


def test_handler_success():
    event = {"key": "value"}
    context = MagicMock()
    response = lambda_handler(event, context)
    assert response["statusCode"] == 200
```

参考: [pytest](https://docs.pytest.org/)

### リンター・フォーマッター（ruff）

```toml
# pyproject.toml
[tool.ruff]
target-version = "py313"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

参考: [Ruff](https://docs.astral.sh/ruff/)

### 型チェック（mypy）

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true
```

参考: [mypy](https://mypy.readthedocs.io/)

## IaC

### 原則

- **AWS リソースの操作は必ず IaC（CDK）経由で実行**
- マネジメントコンソールでの手動操作は禁止
- AWS CLI での直接操作も禁止
- 例外: トラブルシューティング時の確認のみ許可（変更は不可）

### AWS リソース命名規則

AWS リソース名は以下の形式で統一する:

```text
<アプリ名>-<環境名>-<AWSサービス名>-<用途>
```

#### 環境名

- `dev`: 開発環境（development）
- `stg`: ステージング環境（staging）
- `prod`: 本番環境（production）

#### AWSサービス名

- `dynamodb`: DynamoDB テーブル
- `s3`: S3 バケット
- `lambda`: Lambda 関数
- `apigateway`: API Gateway
- `cloudfront`: CloudFront ディストリビューション
- `cognito`: Cognito ユーザープール
- `iam`: IAM ロール・ポリシー
- `cloudwatch`: CloudWatch ロググループ
- `eventbridge`: EventBridge ルール・スケジューラー
- `sqs`: SQS キュー
- `sns`: SNS トピック
- `stepfunctions`: Step Functions ステートマシン

#### 命名例

```text
vdbbench-dev-dynamodb-main
vdbbench-dev-lambda-api
vdbbench-dev-s3-data
```

#### 注意事項

- アプリ名は `vdbbench` で統一
- 全て小文字とハイフン（`-`）を使用
- アンダースコア（`_`）は使用しない
- リソース名の長さ制限に注意（S3 バケット名は 63 文字まで）

### AWS CDK

- Stack は機能単位で分割
- Construct は再利用可能に
- Props で設定を外部化
- Lambda の Python コードは CDK プロジェクト内の `functions/` に配置

参考: [AWS CDK Best Practices](https://docs.aws.amazon.com/cdk/v2/guide/best-practices.html)

### cdk-nag

- デプロイ前に必ず実行
- 警告は無視せず対応

参考: [cdk-nag](https://github.com/cdklabs/cdk-nag)

### CDK テスト

- スナップショットテストで CloudFormation テンプレートを検証
- Fine-grained assertions でリソースの詳細をテスト

```typescript
import { Template } from 'aws-cdk-lib/assertions';
import * as cdk from 'aws-cdk-lib';
import { MyStack } from '../lib/my-stack';

test('DynamoDB table created', () => {
  const app = new cdk.App();
  const stack = new MyStack(app, 'TestStack');
  const template = Template.fromStack(stack);

  template.hasResourceProperties('AWS::DynamoDB::Table', {
    BillingMode: 'PAY_PER_REQUEST',
  });
});
```

参考: [CDK Testing](https://docs.aws.amazon.com/cdk/v2/guide/testing.html)

## セキュリティ

### API

- CORS を適切に設定
- レート制限を実装
- 入力値は必ずバリデーション

### データ

- S3 バケットはプライベート
- DynamoDB は暗号化有効
- 機密情報は Secrets Manager または SSM Parameter Store で管理

参考: [AWS Security Best Practices](https://docs.aws.amazon.com/security/)

## GitHub Actions / CI・CD

### AWS 認証: OIDC（OpenID Connect）

GitHub Actions から AWS へのアクセスには OIDC 認証を使用する。静的なアクセスキーは使用しない。

```yaml
- name: Configure AWS credentials
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
    aws-region: ap-northeast-1
```

参考: [GitHub Actions OIDC](https://docs.github.com/ja/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)

## Spec駆動開発

- Spec のフォルダには連番をつけてください
  - {連番}-Spec名
- Spec の各ファイルは必ず日本語で書いてください

### タスク完了条件（tasks.md の個別タスク単位）

tasks.md の各タスクごとに、以下のサイクルを回すこと:

```text
タスク着手（in_progress）
  → コード実装
  → テスト実行（pytest / npm test）
    → fail あり → 修正 → 再テスト → 全 pass するまで繰り返し
    → 全 pass → git commit → git push → タスク完了（completed）
```

ルール:

1. テストが全 pass しない限り、タスクを完了にしてはならない
2. 自分が変更したコード以外のテストが fail した場合も、原因を調査して修正すること
3. 新規コードには対応するテストを追加すること
4. コミットとプッシュはタスク単位で行う
5. コミットメッセージにはタスク番号を含める（例: `feat: 1.1 DynamoDB テーブル作成`）

## ファイル編集

heredoc を使う場合はタイムアウトを設定すること。

## MCP サーバー利用ルール

Kiro が作業を行う際、以下のルールに従って MCP サーバーを活用すること。

### AWS 操作・AWS CDK 編集時

| MCP サーバー                       | 用途                                                                                                     |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `awslabs-core-mcp-server`          | AWS ドキュメント検索（`search_documentation`）、AWS CLI 実行（`call_aws`）、リージョン情報取得、料金確認 |
| `awslabs.cloudtrail-mcp-server`    | CloudTrail イベントの検索・分析（トラブルシューティング時）                                              |
| `iam-policy-autopilot`             | IAM ポリシーの自動生成（Lambda 等のソースコードから最小権限ポリシーを生成）                              |
| `power-aws-infrastructure-as-code` | CDK サンプル・コンストラクトの検索、IaC ドキュメント参照                                                |

### Python / ライブラリ編集時

| MCP サーバー | 用途                                         |
| ------------ | -------------------------------------------- |
| `context7`   | ライブラリの最新ドキュメント・コード例の検索 |

### GitHub 操作時

| MCP サーバー | 用途                                                                            |
| ------------ | ------------------------------------------------------------------------------- |
| `github`     | PR 作成・一覧・レビュー、Issue 管理、コミット履歴確認、ファイル操作、コード検索 |

### ダイアグラム編集時

| MCP サーバー | 用途                                 |
| ------------ | ------------------------------------ |
| `drawio`     | draw.io 形式のダイアグラム表示・編集 |

### MCP サーバー利用の原則

1. **情報の正確性**: 自身の知識だけに頼らず、MCP サーバーで最新情報を確認してから実装する
2. **ドキュメントファースト**: AWS サービスやライブラリの仕様は、まず MCP サーバー経由でドキュメントを検索する
3. **最小権限の原則**: IAM ポリシーは `iam-policy-autopilot` で自動生成し、手動で過剰な権限を付与しない
4. **GitHub 操作の一元化**: GitHub に関する操作は必ず `github` MCP サーバー経由で行い、`gh` CLI の直接実行は避ける
