import * as cdk from "aws-cdk-lib";
import { Annotations, Match, Template } from "aws-cdk-lib/assertions";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { VectorDbBenchmarkStack } from "../../lib/vector-db-benchmark-stack";

describe("cdk-nag AwsSolutions", () => {
  let stack: cdk.Stack;
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    stack = new VectorDbBenchmarkStack(app, "NagTestStack");
    Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
    // Force synthesis to trigger nag checks
    app.synth();
    template = Template.fromStack(stack);
  });

  test("cdk-nag エラーが発生しないこと", () => {
    const errors = Annotations.fromStack(stack).findError(
      "*",
      Match.stringLikeRegexp("AwsSolutions-.*"),
    );
    expect(errors).toHaveLength(0);
  });

  test("cdk-nag 警告が発生しないこと", () => {
    const warnings = Annotations.fromStack(stack).findWarning(
      "*",
      Match.stringLikeRegexp("AwsSolutions-.*"),
    );
    expect(warnings).toHaveLength(0);
  });

  test("ECS クラスターが cdk-nag チェックを通過すること", () => {
    // ECS クラスターリソースが存在することを確認
    template.resourceCountIs("AWS::ECS::Cluster", 1);

    // ECS 関連の nag エラーがないことを確認
    const errors = Annotations.fromStack(stack).findError(
      "*ECS*",
      Match.stringLikeRegexp("AwsSolutions-ECS.*"),
    );
    expect(errors).toHaveLength(0);
  });

  test("ECS タスク定義が cdk-nag チェックを通過すること", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 1);

    const errors = Annotations.fromStack(stack).findError(
      "*TaskDef*",
      Match.stringLikeRegexp("AwsSolutions-.*"),
    );
    expect(errors).toHaveLength(0);
  });

  test("検索テスト Lambda が cdk-nag チェックを通過すること", () => {
    // SearchTest Lambda が存在することを確認（FunctionName で検索）
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "vdbbench-dev-lambda-search-test",
    });

    // Lambda 関連の nag エラーがないことを確認
    const errors = Annotations.fromStack(stack).findError(
      "*SearchTest*",
      Match.stringLikeRegexp("AwsSolutions-.*"),
    );
    expect(errors).toHaveLength(0);
  });
});
