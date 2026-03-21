import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";

describe("NetworkConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    new NetworkConstruct(stack, "Network");
    template = Template.fromStack(stack);
  });

  describe("VPC", () => {
    test("VPC が CIDR 10.0.0.0/16 で作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPC", {
        CidrBlock: "10.0.0.0/16",
      });
    });

    test("ISOLATED サブネットが 2 AZ 分作成される", () => {
      template.resourceCountIs("AWS::EC2::Subnet", 2);
    });

    test("NAT Gateway が存在しない", () => {
      template.resourceCountIs("AWS::EC2::NatGateway", 0);
    });
  });

  describe("VPC Endpoints", () => {
    test("VPC Interface Endpoint が 6 つ、Gateway Endpoint が 1 つ存在する", () => {
      template.resourceCountIs("AWS::EC2::VPCEndpoint", 7);
    });

    test("Secrets Manager の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".secretsmanager",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("CloudWatch Logs の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".logs",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("OpenSearch Serverless の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".aoss",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("S3 Vectors の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".s3vectors",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("ECR API の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".ecr.api",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("ECR Docker の VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".ecr.dkr",
            ],
          ],
        },
        VpcEndpointType: "Interface",
      });
    });

    test("S3 Gateway VPC Endpoint が作成される", () => {
      template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
        ServiceName: {
          "Fn::Join": [
            "",
            [
              "com.amazonaws.",
              { Ref: "AWS::Region" },
              ".s3",
            ],
          ],
        },
        VpcEndpointType: "Gateway",
      });
    });
  });

  describe("Security Groups", () => {
    test("セキュリティグループが 4 つ作成される", () => {
      template.resourceCountIs("AWS::EC2::SecurityGroup", 4);
    });

    test("ECS SG が vdbbench-dev-sg-ecs の名前で作成される", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        GroupName: "vdbbench-dev-sg-ecs",
        GroupDescription: "Security group for ECS Fargate tasks",
      });
    });

    test("Lambda SG から Aurora SG へのポート 5432 のエグレスルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupEgress", {
        IpProtocol: "tcp",
        FromPort: 5432,
        ToPort: 5432,
        Description: "Allow Lambda to Aurora on port 5432",
      });
    });

    test("Lambda SG から VPC EP SG へのポート 443 のエグレスルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupEgress", {
        IpProtocol: "tcp",
        FromPort: 443,
        ToPort: 443,
        Description: "Allow Lambda to VPC endpoints on port 443",
      });
    });

    test("ECS SG から Aurora SG へのポート 5432 のエグレスルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupEgress", {
        IpProtocol: "tcp",
        FromPort: 5432,
        ToPort: 5432,
        Description: "Allow ECS to Aurora on port 5432",
      });
    });

    test("ECS SG から VPC EP SG へのポート 443 のエグレスルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupEgress", {
        IpProtocol: "tcp",
        FromPort: 443,
        ToPort: 443,
        Description: "Allow ECS to VPC endpoints on port 443",
      });
    });

    test("Aurora SG に Lambda SG からのポート 5432 のインバウンドルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
        IpProtocol: "tcp",
        FromPort: 5432,
        ToPort: 5432,
        Description: "Allow inbound from Lambda on port 5432",
      });
    });

    test("Aurora SG に ECS SG からのポート 5432 のインバウンドルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
        IpProtocol: "tcp",
        FromPort: 5432,
        ToPort: 5432,
        Description: "Allow inbound from ECS on port 5432",
      });
    });

    test("VPC EP SG に Lambda SG からのポート 443 のインバウンドルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
        IpProtocol: "tcp",
        FromPort: 443,
        ToPort: 443,
        Description: "Allow inbound from Lambda on port 443",
      });
    });

    test("VPC EP SG に ECS SG からのポート 443 のインバウンドルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
        IpProtocol: "tcp",
        FromPort: 443,
        ToPort: 443,
        Description: "Allow inbound from ECS on port 443",
      });
    });
  });
});
