import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks, NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";
import { AuroraConstruct } from "./constructs/aurora";
import { NetworkConstruct } from "./constructs/network";
import { OpenSearchConstruct } from "./constructs/opensearch";
import { VerifyFunctionConstruct } from "./constructs/verify-function";

export class AwsLabStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // 1. Network: VPC, Subnets, Security Groups, VPC Endpoints
    const network = new NetworkConstruct(this, "Network");

    // 2. Aurora: Serverless v2 (pgvector)
    const aurora = new AuroraConstruct(this, "Aurora", {
      vpc: network.vpc,
      auroraSg: network.auroraSg,
    });

    // 3. Lambda IAM Role: 循環依存を回避するため先に作成
    const lambdaRole = new iam.Role(this, "VerifyFunctionRole", {
      roleName: "awslab-dev-iam-lambda-vector-verify",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // 4. OpenSearch Serverless: lambdaRole ARN を渡す
    const openSearch = new OpenSearchConstruct(this, "OpenSearch", {
      vpc: network.vpc,
      vpcEndpointSg: network.vpcEndpointSg,
      lambdaRoleArn: lambdaRole.roleArn,
    });

    // 5. VerifyFunction: 事前作成した role を渡す（opensearchEndpoint は後で設定）
    const verifyFunction = new VerifyFunctionConstruct(
      this,
      "VerifyFunction",
      {
        vpc: network.vpc,
        lambdaSg: network.lambdaSg,
        auroraCluster: aurora.cluster,
        auroraSecret: aurora.secret,
        role: lambdaRole,
      },
    );

    // 6. OpenSearch エンドポイントを Lambda 環境変数に追加
    verifyFunction.function.addEnvironment(
      "OPENSEARCH_ENDPOINT",
      openSearch.collectionEndpoint,
    );

    // Construct 間の依存関係
    aurora.node.addDependency(network);
    openSearch.node.addDependency(network);
    verifyFunction.node.addDependency(aurora);
    verifyFunction.node.addDependency(network);

    // cdk-nag: AwsSolutionsChecks を適用
    Aspects.of(this).add(new AwsSolutionsChecks({ verbose: true }));

    // cdk-nag suppressions
    this.addNagSuppressions(lambdaRole);
  }

  private addNagSuppressions(lambdaRole: iam.Role): void {
    // Lambda IAM Role: ワイルドカードリソースの抑制
    NagSuppressions.addResourceSuppressions(
      lambdaRole,
      [
        {
          id: "AwsSolutions-IAM4",
          reason:
            "AWSLambdaVPCAccessExecutionRole is required for Lambda VPC access (ENI management)",
        },
      ],
      true,
    );

    // スタック全体: Lambda 関連の抑制
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason:
          "Wildcard permissions required for aoss:APIAccessAll (OpenSearch Serverless does not support resource-level permissions) and Secrets Manager access",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AWSLambdaVPCAccessExecutionRole managed policy is required for Lambda VPC networking",
      },
      {
        id: "AwsSolutions-L1",
        reason:
          "Python 3.13 is the latest supported Lambda runtime at time of implementation",
      },
      {
        id: "AwsSolutions-RDS6",
        reason:
          "IAM authentication is not used; Secrets Manager credentials are used for Aurora access",
      },
      {
        id: "AwsSolutions-RDS10",
        reason:
          "Deletion protection is intentionally disabled for dev/verification environment to allow cdk destroy",
      },
      {
        id: "AwsSolutions-RDS11",
        reason:
          "Default PostgreSQL port 5432 is used; non-standard port is not required for this verification environment",
      },
      {
        id: "AwsSolutions-RDS14",
        reason:
          "Aurora backtracking is not supported on Aurora PostgreSQL Serverless v2",
      },
      {
        id: "AwsSolutions-RDS16",
        reason:
          "Aurora Serverless v2 does not support enabling Activity Stream at the cluster level",
      },
      {
        id: "AwsSolutions-VPC7",
        reason:
          "VPC Flow Logs are not required for this short-lived verification environment",
      },
      {
        id: "AwsSolutions-EC23",
        reason:
          "Security groups are configured with specific rules; no 0.0.0.0/0 ingress is used",
      },
      {
        id: "AwsSolutions-SMG4",
        reason:
          "Automatic rotation for Aurora Secrets Manager secret is not configured for this short-lived verification environment",
      },
      {
        id: "AwsSolutions-RDS2",
        reason:
          "Aurora Serverless v2 storage encryption is enabled by default; explicit configuration is not required",
      },
    ]);
  }
}
