import * as cdk from "aws-cdk-lib";
import { Annotations, Match } from "aws-cdk-lib/assertions";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { AwsPrivateLabStack } from "../../lib/aws-private-lab-stack";

describe("cdk-nag AwsSolutions", () => {
  let stack: cdk.Stack;

  beforeAll(() => {
    const app = new cdk.App();
    stack = new AwsPrivateLabStack(app, "NagTestStack");
    Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
    // Force synthesis to trigger nag checks
    app.synth();
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
});
