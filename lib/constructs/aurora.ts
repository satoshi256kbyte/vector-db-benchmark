import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface AuroraConstructProps {
  vpc: ec2.Vpc;
  auroraSg: ec2.SecurityGroup;
}

export class AuroraConstruct extends Construct {
  readonly cluster: rds.DatabaseCluster;
  readonly secret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props: AuroraConstructProps) {
    super(scope, id);

    this.cluster = new rds.DatabaseCluster(this, "Cluster", {
      clusterIdentifier: "vdbbench-dev-aurora-pgvector",
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_4,
      }),
      serverlessV2MinCapacity: 0.5,
      serverlessV2MaxCapacity: 16,
      writer: rds.ClusterInstance.serverlessV2("writer"),
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [props.auroraSg],
      credentials: rds.Credentials.fromGeneratedSecret("postgres"),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      deletionProtection: false,
    });

    this.secret = this.cluster.secret!;
  }
}
