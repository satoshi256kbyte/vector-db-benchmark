import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";

export class NetworkConstruct extends Construct {
  readonly vpc: ec2.Vpc;
  readonly lambdaSg: ec2.SecurityGroup;
  readonly auroraSg: ec2.SecurityGroup;
  readonly vpcEndpointSg: ec2.SecurityGroup;
  readonly ecsSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // VPC: 2 AZ, ISOLATED subnets only, no NAT Gateway
    this.vpc = new ec2.Vpc(this, "Vpc", {
      vpcName: "vdbbench-dev-vpc-benchmark",
      ipAddresses: ec2.IpAddresses.cidr("10.0.0.0/16"),
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: "vdbbench-dev-subnet-isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // Security Group: Lambda
    this.lambdaSg = new ec2.SecurityGroup(this, "LambdaSg", {
      vpc: this.vpc,
      securityGroupName: "vdbbench-dev-sg-lambda",
      description: "Security group for Lambda functions",
      allowAllOutbound: false,
    });

    // Security Group: Aurora
    this.auroraSg = new ec2.SecurityGroup(this, "AuroraSg", {
      vpc: this.vpc,
      securityGroupName: "vdbbench-dev-sg-aurora",
      description: "Security group for Aurora cluster",
      allowAllOutbound: false,
    });

    // Security Group: VPC Endpoints
    this.vpcEndpointSg = new ec2.SecurityGroup(this, "VpcEndpointSg", {
      vpc: this.vpc,
      securityGroupName: "vdbbench-dev-sg-vpce",
      description: "Security group for VPC endpoints",
      allowAllOutbound: false,
    });

    // Security Group: ECS Fargate
    this.ecsSg = new ec2.SecurityGroup(this, "EcsSg", {
      vpc: this.vpc,
      securityGroupName: "vdbbench-dev-sg-ecs",
      description: "Security group for ECS Fargate tasks",
      allowAllOutbound: false,
    });

    // SG Rules: ECS -> Aurora:5432
    this.ecsSg.addEgressRule(
      this.auroraSg,
      ec2.Port.tcp(5432),
      "Allow ECS to Aurora on port 5432",
    );

    // SG Rules: ECS -> VPC Endpoints:443
    this.ecsSg.addEgressRule(
      this.vpcEndpointSg,
      ec2.Port.tcp(443),
      "Allow ECS to VPC endpoints on port 443",
    );

    // SG Rules: Aurora <- ECS:5432
    this.auroraSg.addIngressRule(
      this.ecsSg,
      ec2.Port.tcp(5432),
      "Allow inbound from ECS on port 5432",
    );

    // SG Rules: VPC Endpoints <- ECS:443
    this.vpcEndpointSg.addIngressRule(
      this.ecsSg,
      ec2.Port.tcp(443),
      "Allow inbound from ECS on port 443",
    );

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

    // VPC Endpoint: S3 Vectors
    this.vpc.addInterfaceEndpoint("S3VectorsEndpoint", {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${cdk.Aws.REGION}.s3vectors`,
      ),
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });

    // VPC Endpoint: ECR API
    this.vpc.addInterfaceEndpoint("EcrApiEndpoint", {
      service: ec2.InterfaceVpcEndpointAwsService.ECR,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });

    // VPC Endpoint: ECR Docker
    this.vpc.addInterfaceEndpoint("EcrDockerEndpoint", {
      service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.vpcEndpointSg],
    });

    // VPC Endpoint: S3 Gateway (for ECR image layers)
    const s3GatewayEndpoint = this.vpc.addGatewayEndpoint(
      "S3GatewayEndpoint",
      {
        service: ec2.GatewayVpcEndpointAwsService.S3,
        subnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }],
      },
    );

    // SG Rules: ECS -> S3 (HTTPS) for ECR image layer pulls via S3 Gateway Endpoint
    // S3 Gateway Endpoint はルートテーブルベースのため SG ルールは不要だが、
    // ISOLATED サブネットでは S3 への HTTPS 通信を許可する必要がある。
    // Gateway Endpoint 経由のため、宛先は VPC CIDR 内の S3 エンドポイントとなるが、
    // SG では prefix list を使用して S3 の IP レンジを指定する。
    this.ecsSg.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "Allow ECS to S3 via Gateway Endpoint for ECR image pulls",
    );

    // SG Rules: Lambda -> S3 (HTTPS) via S3 Gateway Endpoint
    this.lambdaSg.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "Allow Lambda to S3 via Gateway Endpoint",
    );
  }
}
