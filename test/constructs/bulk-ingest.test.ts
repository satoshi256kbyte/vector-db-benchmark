import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";
import { AuroraConstruct } from "../../lib/constructs/aurora";
import { BulkIngestConstruct } from "../../lib/constructs/bulk-ingest";

describe("BulkIngestConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const network = new NetworkConstruct(stack, "Network");
    const aurora = new AuroraConstruct(stack, "Aurora", {
      vpc: network.vpc,
      auroraSg: network.auroraSg,
    });
    new BulkIngestConstruct(stack, "BulkIngest", {
      vpc: network.vpc,
      ecsSg: network.ecsSg,
      auroraCluster: aurora.cluster,
      auroraSecret: aurora.secret,
      opensearchCollectionEndpoint:
        "https://dummy-endpoint.aoss.amazonaws.com",
      s3vectorsBucketName: "vdbbench-dev-s3vectors-benchmark",
      s3vectorsIndexName: "embeddings",
    });
    template = Template.fromStack(stack);
  });

  describe("ECS Cluster", () => {
    test("ECS クラスターが vdbbench-dev-ecs-benchmark の名前で作成される", () => {
      template.hasResourceProperties("AWS::ECS::Cluster", {
        ClusterName: "vdbbench-dev-ecs-benchmark",
      });
    });
  });

  describe("Fargate Task Definition", () => {
    test("タスク定義のメモリが 4096 MB である", () => {
      template.hasResourceProperties(
        "AWS::ECS::TaskDefinition",
        {
          Memory: "4096",
          RequiresCompatibilities: ["FARGATE"],
        },
      );
    });

    test("タスク定義の vCPU が 2048 である", () => {
      template.hasResourceProperties(
        "AWS::ECS::TaskDefinition",
        {
          Cpu: "2048",
        },
      );
    });
  });

  describe("Container Environment Variables", () => {
    test("コンテナに AURORA_SECRET_ARN 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "AURORA_SECRET_ARN",
              }),
            ]),
          }),
        ]),
      });
    });

    test("コンテナに AURORA_CLUSTER_ENDPOINT 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "AURORA_CLUSTER_ENDPOINT",
              }),
            ]),
          }),
        ]),
      });
    });

    test("コンテナに OPENSEARCH_ENDPOINT 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "OPENSEARCH_ENDPOINT",
                Value: "https://dummy-endpoint.aoss.amazonaws.com",
              }),
            ]),
          }),
        ]),
      });
    });

    test("コンテナに S3VECTORS_BUCKET_NAME 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "S3VECTORS_BUCKET_NAME",
                Value: "vdbbench-dev-s3vectors-benchmark",
              }),
            ]),
          }),
        ]),
      });
    });

    test("コンテナに S3VECTORS_INDEX_NAME 環境変数が設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "S3VECTORS_INDEX_NAME",
                Value: "embeddings",
              }),
            ]),
          }),
        ]),
      });
    });

    test("コンテナに RECORD_COUNT 環境変数がデフォルト値 100000 で設定される", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              Match.objectLike({
                Name: "RECORD_COUNT",
                Value: "100000",
              }),
            ]),
          }),
        ]),
      });
    });
  });

  describe("IAM Task Role Permissions", () => {
    test("IAM ポリシーに secretsmanager:GetSecretValue が含まれる", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: "secretsmanager:GetSecretValue",
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

    test("IAM ポリシーに s3vectors:PutVectors と s3vectors:DeleteVectors が含まれる", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith([
                "s3vectors:PutVectors",
                "s3vectors:DeleteVectors",
              ]),
              Effect: "Allow",
            }),
          ]),
        }),
      });
    });
  });

  describe("CloudWatch Logs", () => {
    test("ロググループが vdbbench-dev-cloudwatch-ecs-bulk-ingest の名前で作成される", () => {
      template.hasResourceProperties("AWS::Logs::LogGroup", {
        LogGroupName: "vdbbench-dev-cloudwatch-ecs-bulk-ingest",
        RetentionInDays: 7,
      });
    });

    test("コンテナのログドライバーが awslogs で stream prefix が bulk-ingest である", () => {
      template.hasResourceProperties("AWS::ECS::TaskDefinition", {
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            LogConfiguration: Match.objectLike({
              LogDriver: "awslogs",
              Options: Match.objectLike({
                "awslogs-stream-prefix": "bulk-ingest",
              }),
            }),
          }),
        ]),
      });
    });
  });
});
