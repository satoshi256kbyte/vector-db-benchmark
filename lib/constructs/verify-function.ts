import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface VerifyFunctionConstructProps {
  vpc: ec2.Vpc;
  lambdaSg: ec2.SecurityGroup;
  auroraCluster: rds.DatabaseCluster;
  auroraSecret: secretsmanager.ISecret;
  opensearchCollectionEndpoint?: string;
  role?: iam.IRole;
}

export class VerifyFunctionConstruct extends Construct {
  readonly function: lambda.Function;

  constructor(
    scope: Construct,
    id: string,
    props: VerifyFunctionConstructProps,
  ) {
    super(scope, id);

    const environment: Record<string, string> = {
      AURORA_SECRET_ARN: props.auroraSecret.secretArn,
      AURORA_CLUSTER_ENDPOINT:
        props.auroraCluster.clusterEndpoint.hostname,
      POWERTOOLS_SERVICE_NAME: "vector-verify",
      POWERTOOLS_LOG_LEVEL: "INFO",
    };

    if (props.opensearchCollectionEndpoint) {
      environment.OPENSEARCH_ENDPOINT =
        props.opensearchCollectionEndpoint;
    }

    this.function = new lambda.Function(this, "Function", {
      functionName: "awslab-dev-lambda-vector-verify",
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "handler.handler",
      code: lambda.Code.fromAsset("functions/vector-verify"),
      memorySize: 256,
      timeout: cdk.Duration.seconds(300),
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [props.lambdaSg],
      ...(props.role ? { role: props.role as iam.Role } : {}),
      environment,
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
  }
}
