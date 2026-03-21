import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkConstruct } from "../../lib/constructs/network";
import { AuroraConstruct } from "../../lib/constructs/aurora";

describe("AuroraConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const network = new NetworkConstruct(stack, "Network");
    new AuroraConstruct(stack, "Aurora", {
      vpc: network.vpc,
      auroraSg: network.auroraSg,
    });
    template = Template.fromStack(stack);
  });

  test("Aurora DatabaseCluster が作成される", () => {
    template.hasResourceProperties("AWS::RDS::DBCluster", {
      Engine: "aurora-postgresql",
    });
  });

  test("Serverless v2 スケーリング設定が MinCapacity: 0, MaxCapacity: 16 である", () => {
    template.hasResourceProperties("AWS::RDS::DBCluster", {
      ServerlessV2ScalingConfiguration: {
        MinCapacity: 0,
        MaxCapacity: 16,
      },
    });
  });

  test("クラスターの DeletionPolicy が Delete である", () => {
    template.hasResource("AWS::RDS::DBCluster", {
      DeletionPolicy: "Delete",
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
});
