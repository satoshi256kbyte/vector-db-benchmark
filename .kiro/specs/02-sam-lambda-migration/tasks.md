# タスク

## 1. SAM テンプレートの作成とビルド基盤

- [x] 1.1 プロジェクトルートに `template.yaml` を作成する（ビルド専用 SAM テンプレート、VectorVerifyFunction を定義、Python 3.13、CodeUri: functions/vector-verify/）
- [x] 1.2 `.gitignore` に `.aws-sam/` を追加する

## 2. CDK Lambda コンストラクトの修正

- [x] 2.1 `lib/constructs/verify-function.ts` の `bundling` 設定を除去し、`Code.fromAsset(".aws-sam/build/VectorVerifyFunction")` に変更する
- [x] 2.2 `test/constructs/verify-function.test.ts` を更新し、既存テストが修正後のコンストラクトで通ることを確認する
- [x] 2.3 Property 1（SAM ビルド出力参照）と Property 2（Lambda 非コード設定の保全）のプロパティベーステストを fast-check で追加する

## 3. ドキュメント更新

- [x] 3.1 `README.md` を更新する（前提条件に AWS SAM CLI と Docker を追加、デプロイ手順を `sam build --use-container` → `npx cdk deploy` に変更）
- [x] 3.2 `.kiro/steering/2-technology-stack.md` に AWS SAM をビルドツールとして追記する
- [x] 3.3 `.kiro/steering/3-implementation-guide.md` に SAM build ワークフローを追記する
