import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AwsPrivateLabStack } from "../../lib/aws-private-lab-stack";

describe("CDK プロパティテスト", () => {
  let template: Template;
  let templateJson: Record<string, any>;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new AwsPrivateLabStack(app, "PropertyTestStack");
    template = Template.fromStack(stack);
    templateJson = template.toJSON();
  });

  /**
   * プロパティ 1: リソース命名規則の一貫性
   *
   * 任意の CDKスタック内のユーザー定義名を持つリソースに対して、
   * そのリソース名は `awsprivatelab-dev-` で始まるパターンに一致しなければならない。
   *
   * **Validates: Requirements 1.6**
   */
  test("プロパティ 1: ユーザー定義名を持つ全リソースが awsprivatelab-dev- で始まること", () => {
    const resources = templateJson.Resources;
    const namePropertyMap: Record<string, string> = {
      "AWS::EC2::VPC": "Tags",
      "AWS::EC2::SecurityGroup": "GroupName",
      "AWS::Lambda::Function": "FunctionName",
      "AWS::RDS::DBCluster": "DBClusterIdentifier",
      "AWS::IAM::Role": "RoleName",
      "AWS::OpenSearchServerless::Collection": "Name",
    };

    const violations: string[] = [];

    for (const [logicalId, resource] of Object.entries(resources)) {
      const res = resource as Record<string, any>;
      const resourceType = res.Type as string;

      // VPC: check Tags with Key "Name"
      if (resourceType === "AWS::EC2::VPC") {
        const tags = res.Properties?.Tags as
          | Array<{ Key: string; Value: string }>
          | undefined;
        if (tags) {
          const nameTag = tags.find((t) => t.Key === "Name");
          if (nameTag && !nameTag.Value.startsWith("awsprivatelab-dev-")) {
            violations.push(
              `${logicalId} (${resourceType}): Tag Name = "${nameTag.Value}" does not start with "awsprivatelab-dev-"`,
            );
          }
        }
        continue;
      }

      // Other resources: check their specific name property
      const nameProp = namePropertyMap[resourceType];
      if (nameProp && res.Properties?.[nameProp]) {
        const nameValue = res.Properties[nameProp] as string;
        if (
          typeof nameValue === "string" &&
          !nameValue.startsWith("awsprivatelab-dev-")
        ) {
          violations.push(
            `${logicalId} (${resourceType}): ${nameProp} = "${nameValue}" does not start with "awsprivatelab-dev-"`,
          );
        }
      }
    }

    expect(violations).toEqual([]);
  });

  /**
   * プロパティ 4: 全リソースの削除ポリシー
   *
   * 任意の 合成されたCloudFormationテンプレート内の DeletionPolicy をサポートするリソースに対して、
   * その DeletionPolicy は "Delete" に設定されていなければならない。
   *
   * Note: AWS::CloudFormation::CustomResource と Custom::* タイプは除外する。
   *
   * **Validates: Requirements 6.1, 6.3**
   */
  test("プロパティ 4: DeletionPolicy を持つ全リソースが Delete に設定されていること", () => {
    const resources = templateJson.Resources;
    const violations: string[] = [];

    for (const [logicalId, resource] of Object.entries(resources)) {
      const res = resource as Record<string, any>;
      const resourceType = res.Type as string;

      // Exclude custom resources
      if (
        resourceType === "AWS::CloudFormation::CustomResource" ||
        resourceType.startsWith("Custom::")
      ) {
        continue;
      }

      // Check resources that have DeletionPolicy explicitly set
      if (
        res.DeletionPolicy !== undefined &&
        res.DeletionPolicy !== "Delete"
      ) {
        violations.push(
          `${logicalId} (${resourceType}): DeletionPolicy = "${res.DeletionPolicy}" (expected "Delete")`,
        );
      }
    }

    expect(violations).toEqual([]);
  });
});
