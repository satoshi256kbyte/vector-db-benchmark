# 要件定義書

## はじめに

Lambda 関数のビルド方式を CDK bundling から AWS SAM build に移行する。
現在、CDK の bundling で Lambda 関数の依存ライブラリをパッケージングしているが、psycopg2 のクロスプラットフォームバイナリ問題により Lambda が動作しない。
`sam build` を使用すれば Docker コンテナ内で Python 依存ライブラリをビルドできるため、この問題を解決できる。

デプロイは引き続き CDK に統一する。SAM はビルドツールとしてのみ使用し、`sam build` の出力ディレクトリを CDK の `Code.fromAsset` で参照する。
これにより CloudFormation Export や `!ImportValue` は不要となり、CDK が全リソースを一元管理できる。

## 用語集

- **CDK_Stack**: AWS CDK で管理される CloudFormation スタック（VectorDbBenchmarkStack）。VPC、Aurora、OpenSearch、S3 Vectors、IAM ロール、Lambda 関数等の全リソースを管理する
- **SAM_Template**: AWS SAM の template.yaml ファイル。`sam build` でのビルド対象 Lambda 関数を定義する。デプロイには使用しない
- **SAM_Build**: `sam build` コマンド。Docker コンテナ内で Python 依存ライブラリをビルドし、Lambda 実行環境（x86_64 Linux）と互換性のあるバイナリを生成する
- **SAM_Build_Output**: `sam build` の出力ディレクトリ（`.aws-sam/build/`）。CDK の `Code.fromAsset` で参照される
- **Verify_Function_Construct**: CDK の Lambda 関数コンストラクト（lib/constructs/verify-function.ts）

## 要件

### 要件 1: SAM テンプレートの作成（ビルド専用）

**ユーザーストーリー:** 開発者として、`sam build` で Docker コンテナ内で Python 依存ライブラリをビルドするための SAM テンプレートを作成したい。psycopg2-binary が Lambda 実行環境と互換性のあるバイナリとしてビルドされるようにするため。

#### 受け入れ基準

1. THE SAM_Template SHALL プロジェクトルートに template.yaml として配置される
2. THE SAM_Template SHALL Python 3.13 ランタイムの Lambda 関数（vector-verify）を定義する
3. THE SAM_Template SHALL 各 Lambda 関数の CodeUri として functions/ 配下の対応するディレクトリを指定する
4. THE SAM_Template SHALL ビルド専用であり、デプロイ設定（VPC、IAM ロール、環境変数等）は最小限とする
5. THE SAM_Template SHALL 将来の Lambda 関数追加に対応できる拡張可能な構造を持つ
6. WHEN `sam build --use-container` が実行された場合、THE SAM_Build SHALL Docker コンテナ内で functions/vector-verify/requirements.txt に記載された全ライブラリをインストールする
7. WHEN SAM_Build が完了した場合、THE SAM_Build_Output SHALL psycopg2-binary を含む全依存ライブラリが Lambda 実行環境（x86_64 Linux）と互換性のある状態になる

### 要件 2: CDK Lambda コンストラクトの修正（SAM ビルド出力を参照）

**ユーザーストーリー:** 開発者として、CDK の Lambda コンストラクトが SAM_Build_Output を参照するように修正したい。CDK bundling を除去し、`sam build` でビルドされた成果物を使用するため。

#### 受け入れ基準

1. THE Verify_Function_Construct SHALL CDK bundling 設定を含まず、`Code.fromAsset` で SAM_Build_Output ディレクトリを参照する
2. THE Verify_Function_Construct SHALL IAM ロール、セキュリティグループ、VPC 設定、環境変数の設定を引き続き管理する
3. THE Verify_Function_Construct SHALL メモリサイズ、タイムアウト等の Lambda 設定を引き続き管理する
4. WHEN `sam build` が事前に実行されていない場合、THE CDK deploy SHALL 明確なエラーメッセージを表示する

### 要件 3: デプロイワークフローの確立

**ユーザーストーリー:** 開発者として、`sam build` → `cdk deploy` の一貫したデプロイワークフローを確立したい。ビルドとデプロイの手順を明確にするため。

#### 受け入れ基準

1. THE デプロイ手順 SHALL `sam build --use-container` → `npx cdk deploy` の2ステップで完結する
2. WHEN `sam build --use-container` が実行された場合、THE SAM_Build_Output SHALL `.aws-sam/build/` ディレクトリに生成される
3. WHEN `npx cdk deploy` が実行された場合、THE CDK_Stack SHALL SAM_Build_Output を Lambda 関数のコードとして使用する
4. THE デプロイ手順 SHALL CDK が全リソース（インフラ + Lambda）を単一スタックでデプロイする

### 要件 4: ドキュメント更新

**ユーザーストーリー:** 開発者として、SAM ビルド導入に伴いプロジェクトのドキュメントを更新したい。新しいビルド・デプロイ手順と技術スタックの変更を正確に反映するため。

#### 受け入れ基準

1. THE README.md SHALL デプロイ手順を `sam build --use-container` → `npx cdk deploy` の順序で記載する
2. THE README.md SHALL 前提条件に AWS SAM CLI と Docker を追加する
3. THE 技術スタックドキュメント（2-technology-stack.md）SHALL AWS SAM をビルドツールとして追記する
4. THE 実装ガイドドキュメント（3-implementation-guide.md）SHALL SAM build を使用した Lambda 関数のビルド手順を追記する
5. THE .gitignore SHALL `.aws-sam/` ディレクトリを除外対象に追加する
