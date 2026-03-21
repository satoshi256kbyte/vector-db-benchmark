import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";
import { AuroraConstruct } from "../../lib/constructs/aurora";
import { VerifyFunctionConstruct } from "../../lib/constructs/verify-function";

describe("VerifyFunctionConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const network = new NetworkConstruct(stack, "Network");
    const aurora = new AuroraConstruct(stack, "Aurora", {
      vpc: network.vpc,
      auroraSg: network.auroraSg,
    });
    new VerifyFunctionConstruct(stack, "VerifyFunction", {
      vpc: network.vpc,
      lambdaSg: network.lambdaSg,
      auroraCluster: aurora.cluster,
      auroraSecret: aurora.secret,
      opensearchCollectionEndpoint:
        "https://dummy-endpoint.aoss.amazonaws.com",
      s3vectorsBucketName: "vdbbench-dev-s3vectors-benchmark",
      s3vectorsIndexName: "embeddings",
    });
    template = Template.fromStack(stack);
  });

  test("Lambda 関数が Python 3.13 ランタイムで作成される", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Runtime: "python3.13",
    });
  });

  test("Lambda 関数のメモリが 256 MB である", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      MemorySize: 256,
    });
  });

  test("Lambda 関数のタイムアウトが 300 秒である", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Timeout: 300,
    });
  });

  test("Lambda 関数が VPC 内に配置される", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      VpcConfig: Match.objectLike({
        SubnetIds: Match.anyValue(),
        SecurityGroupIds: Match.anyValue(),
      }),
    });
  });

  test("Lambda 関数に正しい環境変数が設定される", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: {
        Variables: Match.objectLike({
          AURORA_SECRET_ARN: Match.anyValue(),
          AURORA_CLUSTER_ENDPOINT: Match.anyValue(),
          OPENSEARCH_ENDPOINT:
            "https://dummy-endpoint.aoss.amazonaws.com",
          POWERTOOLS_SERVICE_NAME: "vector-verify",
          POWERTOOLS_LOG_LEVEL: "INFO",
        }),
      },
    });
  });

  test("Lambda 関数に S3 Vectors 環境変数が設定される", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: {
        Variables: Match.objectLike({
          S3VECTORS_BUCKET_NAME:
            "vdbbench-dev-s3vectors-benchmark",
          S3VECTORS_INDEX_NAME: "embeddings",
        }),
      },
    });
  });

  test("IAM ポリシーに s3vectors 権限が含まれる", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              "s3vectors:PutVectors",
              "s3vectors:GetVectors",
              "s3vectors:QueryVectors",
              "s3vectors:DeleteVectors",
            ]),
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  test("IAM ポリシーに aoss:APIAccessAll が含まれる", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "aoss:APIAccessAll",
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  test("IAM ポリシーに secretsmanager:GetSecretValue が含まれる", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(["secretsmanager:GetSecretValue"]),
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });
});
