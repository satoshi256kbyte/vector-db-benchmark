import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";
import { AuroraConstruct } from "../../lib/constructs/aurora";
import { SearchTestConstruct } from "../../lib/constructs/search-test";

describe("SearchTestConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const network = new NetworkConstruct(stack, "Network");
    const aurora = new AuroraConstruct(stack, "Aurora", {
      vpc: network.vpc,
      auroraSg: network.auroraSg,
    });
    new SearchTestConstruct(stack, "SearchTest", {
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

  describe("Lambda 関数の基本構成", () => {
    it("Lambda 関数名が vdbbench-dev-lambda-search-test である", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: "vdbbench-dev-lambda-search-test",
      });
    });

    it("Lambda 関数が Python 3.13 ランタイムで作成される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Runtime: "python3.13",
      });
    });

    it("Lambda 関数のハンドラーが handler.handler である", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Handler: "handler.handler",
      });
    });

    it("Lambda 関数のメモリが 512 MB である", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        MemorySize: 512,
      });
    });

    it("Lambda 関数のタイムアウトが 300 秒である", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Timeout: 300,
      });
    });
  });

  describe("VPC 配置", () => {
    it("Lambda 関数が VPC 内の ISOLATED サブネットに配置される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        VpcConfig: Match.objectLike({
          SubnetIds: Match.anyValue(),
          SecurityGroupIds: Match.anyValue(),
        }),
      });
    });
  });

  describe("環境変数", () => {
    it("AURORA_SECRET_ARN 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            AURORA_SECRET_ARN: Match.anyValue(),
          }),
        },
      });
    });

    it("AURORA_CLUSTER_ENDPOINT 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            AURORA_CLUSTER_ENDPOINT: Match.anyValue(),
          }),
        },
      });
    });

    it("OPENSEARCH_ENDPOINT 環境変数が正しい値で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            OPENSEARCH_ENDPOINT:
              "https://dummy-endpoint.aoss.amazonaws.com",
          }),
        },
      });
    });

    it("S3VECTORS_BUCKET_NAME 環境変数が正しい値で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            S3VECTORS_BUCKET_NAME: "vdbbench-dev-s3vectors-benchmark",
          }),
        },
      });
    });

    it("S3VECTORS_INDEX_NAME 環境変数が正しい値で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            S3VECTORS_INDEX_NAME: "embeddings",
          }),
        },
      });
    });

    it("POWERTOOLS_SERVICE_NAME が search-test で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            POWERTOOLS_SERVICE_NAME: "search-test",
          }),
        },
      });
    });

    it("POWERTOOLS_LOG_LEVEL が INFO で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            POWERTOOLS_LOG_LEVEL: "INFO",
          }),
        },
      });
    });
  });

  describe("IAM 権限", () => {
    it("IAM ポリシーに aoss:APIAccessAll が含まれる", () => {
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

    it("IAM ポリシーに s3vectors:QueryVectors と s3vectors:GetVectors が含まれる", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith([
                "s3vectors:QueryVectors",
                "s3vectors:GetVectors",
              ]),
              Effect: "Allow",
            }),
          ]),
        }),
      });
    });

    it("IAM ポリシーに secretsmanager:GetSecretValue が含まれる", () => {
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
});
