import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface BulkIngestConstructProps {
  vpc: ec2.Vpc;
  ecsSg: ec2.SecurityGroup;
  auroraCluster: rds.DatabaseCluster;
  auroraSecret: secretsmanager.ISecret;
  opensearchCollectionEndpoint: string;
  s3vectorsBucketName: string;
  s3vectorsIndexName: string;
}

export class BulkIngestConstruct extends Construct {
  readonly cluster: ecs.Cluster;
  readonly taskDefinition: ecs.FargateTaskDefinition;
  readonly container: ecs.ContainerDefinition;

  constructor(
    scope: Construct,
    id: string,
    props: BulkIngestConstructProps,
  ) {
    super(scope, id);

    // ECS Cluster
    this.cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: "vdbbench-dev-ecs-benchmark",
      vpc: props.vpc,
    });
    this.cluster.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // CloudWatch Logs log group
    const logGroup = new logs.LogGroup(this, "LogGroup", {
      logGroupName: "vdbbench-dev-cloudwatch-ecs-bulk-ingest",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    // Fargate Task Definition
    this.taskDefinition = new ecs.FargateTaskDefinition(
      this,
      "TaskDefinition",
      {
        memoryLimitMiB: 4096,
        cpu: 2048,
        runtimePlatform: {
          cpuArchitecture: ecs.CpuArchitecture.X86_64,
          operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        },
      },
    );

    // Container
    this.container = this.taskDefinition.addContainer("BulkIngestContainer", {
      image: ecs.ContainerImage.fromAsset("ecs/bulk-ingest", {
        platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
      }),
      logging: ecs.LogDrivers.awsLogs({
        logGroup,
        streamPrefix: "bulk-ingest",
      }),
      environment: {
        AURORA_SECRET_ARN: props.auroraSecret.secretArn,
        AURORA_CLUSTER_ENDPOINT:
          props.auroraCluster.clusterEndpoint.hostname,
        OPENSEARCH_ENDPOINT: props.opensearchCollectionEndpoint,
        S3VECTORS_BUCKET_NAME: props.s3vectorsBucketName,
        S3VECTORS_INDEX_NAME: props.s3vectorsIndexName,
        RECORD_COUNT: "100000",
      },
    });

    // IAM task role permissions
    this.taskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [props.auroraSecret.secretArn],
      }),
    );

    this.taskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["aoss:APIAccessAll"],
        resources: ["*"],
      }),
    );

    this.taskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: [
          "s3vectors:PutVectors",
          "s3vectors:DeleteVectors",
          "s3vectors:ListVectors",
        ],
        resources: ["*"],
      }),
    );
  }
}
