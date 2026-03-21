import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AwsLabStack } from "../lib/aws-lab-stack";

test("Stack creates successfully", () => {
  const app = new cdk.App();
  const stack = new AwsLabStack(app, "TestStack");
  const template = Template.fromStack(stack);

  // スタックが空でもエラーにならないことを確認
  expect(template.toJSON()).toBeDefined();
});
