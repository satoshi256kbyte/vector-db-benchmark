import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";

export class NetworkConstruct extends Construct {
  readonly vpc: ec2.Vpc;
  readonly lambdaSg: ec2.SecurityGroup;
  readonly auroraSg: ec2.SecurityGroup;
  readonly vpcEndpointSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // VPC: 2 AZ, ISOLATED subnets only, no NAT Gateway
    this.vpc = new ec2.Vpc(this, "Vpc", {
      vpcName: "awslab-dev-vpc-benchmark",
      ipAddresses: ec2.IpAddresses.cidr("10.0.0.0/16"),
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: "awslab-dev-subnet-isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // Security Group: Lambda
    this.lambdaSg = new ec2.SecurityGroup(this, "LambdaSg", {
      vpc: this.vpc,
      securityGroupName: "awslab-dev-sg-lambda",
      description: "Security group for Lambda functions",
      allowAllOutbound: false,
    });

    // Security Group: Aurora
    this.auroraSg = new ec2.SecurityGroup(this, "AuroraSg", {
      vpc: this.vpc,
      securityGroupName: "awslab-dev-sg-aurora",
      description: "Security group for Aurora cluster",
      allowAllOutbound: false,
    });

    // Security Group: VPC Endpoints
    this.vpcEndpointSg = new ec2.SecurityGroup(this, "VpcEndpointSg", {
      vpc: this.vpc,
      securityGroupName: "awslab-dev-sg-vpce",
      description: "Security group for VPC endpoints",
      allowAllOutbound: false,
    });

    // SG Rules: Lambda -> Aurora:5432
    this.lambdaSg.addEgressRule(
      this.auroraSg,
      ec2.Port.tcp(5432),
      "Allow Lambda to Aurora on port 5432",
    );
    this.auroraSg.addIngressRule(
      this.lambdaSg,
      ec2.Port.tcp(5432),
      "Allow inbound from Lambda on port 5432",
    );

    // SG Rules: Lambda -> VPC Endpoints:443
    this.lambdaSg.addEgressRule(
      this.vpcEndpointSg,
      ec2.Port.tcp(443),
      "Allow Lambda to VPC endpoints on port 443",
    );
    this.vpcEndpointSg.addIngressRule(
      this.lambdaSg,
      ec2.Port.tcp(443),
      "Allow inbound from Lambda on port 443",
    );

    // VPC Endpoint: Secrets Manager
    this.vpc.addInterfaceEndpoint("SecretsManagerEndpoint", {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });

    // VPC Endpoint: CloudWatch Logs
    this.vpc.addInterfaceEndpoint("CloudWatchLogsEndpoint", {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });

    // VPC Endpoint: OpenSearch Serverless (aoss)
    this.vpc.addInterfaceEndpoint("OpenSearchServerlessEndpoint", {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${cdk.Aws.REGION}.aoss`,
      ),
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });
  }
}
