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
    test("VPC Interface Endpoint が 4 つ存在する", () => {
      template.resourceCountIs("AWS::EC2::VPCEndpoint", 4);
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
  });

  describe("Security Groups", () => {
    test("セキュリティグループが 3 つ作成される", () => {
      template.resourceCountIs("AWS::EC2::SecurityGroup", 3);
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

    test("Aurora SG に Lambda SG からのポート 5432 のインバウンドルールが存在する", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
        IpProtocol: "tcp",
        FromPort: 5432,
        ToPort: 5432,
        Description: "Allow inbound from Lambda on port 5432",
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
  });
});
