import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface SearchTestConstructProps {
  vpc: ec2.Vpc;
  lambdaSg: ec2.SecurityGroup;
  auroraCluster: rds.DatabaseCluster;
  auroraSecret: secretsmanager.ISecret;
  opensearchCollectionEndpoint: string;
  s3vectorsBucketName: string;
  s3vectorsIndexName: string;
  role?: iam.IRole;
}

export class SearchTestConstruct extends Construct {
  readonly function: lambda.Function;

  constructor(
    scope: Construct,
    id: string,
    props: SearchTestConstructProps,
  ) {
    super(scope, id);

    this.function = new lambda.Function(this, "Function", {
      functionName: "vdbbench-dev-lambda-search-test",
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(".aws-sam/build/SearchTestFunction"),
      memorySize: 512,
      timeout: cdk.Duration.seconds(300),
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [props.lambdaSg],
      ...(props.role ? { role: props.role as iam.Role } : {}),
      environment: {
        AURORA_SECRET_ARN: props.auroraSecret.secretArn,
        AURORA_CLUSTER_ENDPOINT:
          props.auroraCluster.clusterEndpoint.hostname,
        OPENSEARCH_ENDPOINT: props.opensearchCollectionEndpoint,
        S3VECTORS_BUCKET_NAME: props.s3vectorsBucketName,
        S3VECTORS_INDEX_NAME: props.s3vectorsIndexName,
        POWERTOOLS_SERVICE_NAME: "search-test",
        POWERTOOLS_LOG_LEVEL: "INFO",
      },
    });

    // Grant Secrets Manager read access for Aurora credentials
    props.auroraSecret.grantRead(this.function);

    // Grant OpenSearch Serverless API access
    this.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["aoss:APIAccessAll"],
        resources: ["*"],
      }),
    );

    // Grant S3 Vectors access (query and get for search testing)
    this.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3vectors:QueryVectors", "s3vectors:GetVectors"],
        resources: ["*"],
      }),
    );
  }
}
