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

    it("Lambda 関数のハンドラーが handler.semantic_cache_handler である", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Handler: "handler.semantic_cache_handler",
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

    it("SIMILARITY_THRESHOLD 環境変数が 0.95 で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            SIMILARITY_THRESHOLD: "0.95",
          }),
        },
      });
    });

    it("CACHE_TTL 環境変数が 3600 で設定される", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            CACHE_TTL: "3600",
          }),
        },
      });
    });
  });

  describe("IAM 権限", () => {
    it("IAM ポリシーに aoss:APIAccessAll が含まれない", () => {
      const policies = template.findResources("AWS::IAM::Policy");
      for (const [, policy] of Object.entries(policies)) {
        const statements =
          (policy as Record<string, Record<string, Record<string, unknown[]>>>)
            .Properties?.PolicyDocument?.Statement ?? [];
        for (const stmt of statements) {
          const action = (stmt as Record<string, unknown>).Action;
          expect(action).not.toBe("aoss:APIAccessAll");
          if (Array.isArray(action)) {
            expect(action).not.toContain("aoss:APIAccessAll");
          }
        }
      }
    });

    it("IAM ポリシーに s3vectors:QueryVectors と s3vectors:GetVectors が含まれない", () => {
      const policies = template.findResources("AWS::IAM::Policy");
      for (const [, policy] of Object.entries(policies)) {
        const statements =
          (policy as Record<string, Record<string, Record<string, unknown[]>>>)
            .Properties?.PolicyDocument?.Statement ?? [];
        for (const stmt of statements) {
          const action = (stmt as Record<string, unknown>).Action;
          if (Array.isArray(action)) {
            expect(action).not.toContain("s3vectors:QueryVectors");
            expect(action).not.toContain("s3vectors:GetVectors");
          } else {
            expect(action).not.toBe("s3vectors:QueryVectors");
            expect(action).not.toBe("s3vectors:GetVectors");
          }
        }
      }
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

    it("IAM ポリシーに bedrock:InvokeModel が含まれる", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: "bedrock:InvokeModel",
              Effect: "Allow",
            }),
          ]),
        }),
      });
    });

    it("bedrock:InvokeModel のリソースが Titan Embeddings モデルに限定される", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: "bedrock:InvokeModel",
              Effect: "Allow",
              Resource:
                "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-*",
            }),
          ]),
        }),
      });
    });
  });
});
