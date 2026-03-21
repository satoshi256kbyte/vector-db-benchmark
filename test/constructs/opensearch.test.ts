import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";
import { OpenSearchConstruct } from "../../lib/constructs/opensearch";

describe("OpenSearchConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const network = new NetworkConstruct(stack, "Network");
    new OpenSearchConstruct(stack, "OpenSearch", {
      vpc: network.vpc,
      vpcEndpointSg: network.vpcEndpointSg,
      lambdaRoleArn: "arn:aws:iam::123456789012:role/test-role",
    });
    template = Template.fromStack(stack);
  });

  test("OpenSearch Serverless コレクションが VECTORSEARCH タイプで作成される", () => {
    template.hasResourceProperties(
      "AWS::OpenSearchServerless::Collection",
      {
        Name: "vdbbench-dev-oss-vector",
        Type: "VECTORSEARCH",
      },
    );
  });

  test("暗号化セキュリティポリシーが作成される", () => {
    template.hasResourceProperties(
      "AWS::OpenSearchServerless::SecurityPolicy",
      {
        Type: "encryption",
      },
    );
  });

  test("ネットワークセキュリティポリシーが作成される", () => {
    template.hasResourceProperties(
      "AWS::OpenSearchServerless::SecurityPolicy",
      {
        Type: "network",
      },
    );
  });

  test("データアクセスポリシーが作成される", () => {
    template.hasResourceProperties(
      "AWS::OpenSearchServerless::AccessPolicy",
      {
        Type: "data",
      },
    );
  });

  test("OpenSearch Serverless VPC Endpoint が作成される", () => {
    template.hasResourceProperties(
      "AWS::OpenSearchServerless::VpcEndpoint",
      {
        Name: "vdbbench-dev-oss-vector-vpce",
      },
    );
  });
});
