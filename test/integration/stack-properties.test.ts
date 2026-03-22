import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { VectorDbBenchmarkStack } from "../../lib/vector-db-benchmark-stack";

describe("CDK プロパティテスト", () => {
  let template: Template;
  let templateJson: Record<string, any>;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new VectorDbBenchmarkStack(app, "PropertyTestStack");
    template = Template.fromStack(stack);
    templateJson = template.toJSON();
  });

  /**
   * プロパティ 1: リソース命名規則の一貫性
   *
   * 任意の CDKスタック内のユーザー定義名を持つリソースに対して、
   * そのリソース名は `vdbbench-dev-` で始まるパターンに一致しなければならない。
   *
   * **Validates: Requirements 1.6**
   */
  test("プロパティ 1: ユーザー定義名を持つ全リソースが vdbbench-dev- で始まること", () => {
    const resources = templateJson.Resources;
    const namePropertyMap: Record<string, string> = {
      "AWS::EC2::VPC": "Tags",
      "AWS::EC2::SecurityGroup": "GroupName",
      "AWS::Lambda::Function": "FunctionName",
      "AWS::RDS::DBCluster": "DBClusterIdentifier",
      "AWS::IAM::Role": "RoleName",
      "AWS::OpenSearchServerless::Collection": "Name",
      "AWS::S3Vectors::VectorBucket": "VectorBucketName",
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
          if (nameTag && !nameTag.Value.startsWith("vdbbench-dev-")) {
            violations.push(
              `${logicalId} (${resourceType}): Tag Name = "${nameTag.Value}" does not start with "vdbbench-dev-"`,
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
          !nameValue.startsWith("vdbbench-dev-")
        ) {
          violations.push(
            `${logicalId} (${resourceType}): ${nameProp} = "${nameValue}" does not start with "vdbbench-dev-"`,
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

  /**
   * プロパティ 7: 新規リソースの削除ポリシー
   *
   * Spec 03 で追加された ECS タスク定義、ECS クラスター、検索テスト Lambda 等の
   * 新規リソースに対して、DeletionPolicy が "Delete" に設定されている、
   * または未設定（CloudFormation デフォルト = Delete）であること。
   *
   * **Validates: Requirements 8.1, 8.2**
   * Feature: 03-vector-benchmark-execution, Property 7: 全リソースの削除ポリシー
   */
  test("プロパティ 7: Spec 03 新規リソースが cdk destroy で完全削除可能であること", () => {
    const resources = templateJson.Resources;

    // Spec 03 で追加された新規リソースタイプ
    const spec03ResourceTypes = [
      "AWS::ECS::Cluster",
      "AWS::ECS::TaskDefinition",
      "AWS::Logs::LogGroup",
    ];

    const violations: string[] = [];

    for (const [logicalId, resource] of Object.entries(resources)) {
      const res = resource as Record<string, any>;
      const resourceType = res.Type as string;

      if (!spec03ResourceTypes.includes(resourceType)) {
        continue;
      }

      // DeletionPolicy が設定されている場合は "Delete" であること
      // 未設定の場合は CloudFormation デフォルト（Delete）が適用される
      if (
        res.DeletionPolicy !== undefined &&
        res.DeletionPolicy !== "Delete"
      ) {
        violations.push(
          `${logicalId} (${resourceType}): DeletionPolicy = "${res.DeletionPolicy}" (expected "Delete")`,
        );
      }

      // UpdateReplacePolicy も同様にチェック
      if (
        res.UpdateReplacePolicy !== undefined &&
        res.UpdateReplacePolicy !== "Delete"
      ) {
        violations.push(
          `${logicalId} (${resourceType}): UpdateReplacePolicy = "${res.UpdateReplacePolicy}" (expected "Delete")`,
        );
      }
    }

    expect(violations).toEqual([]);
  });

  /**
   * 検索テスト Lambda が存在し削除可能であること
   */
  test("プロパティ 7: 検索テスト Lambda が存在し削除ポリシーが正しいこと", () => {
    // SearchTest Lambda が存在することを確認
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "vdbbench-dev-lambda-search-test",
    });

    // Lambda リソースの DeletionPolicy を確認
    const resources = templateJson.Resources;
    for (const [, resource] of Object.entries(resources)) {
      const res = resource as Record<string, any>;
      if (
        res.Type === "AWS::Lambda::Function" &&
        res.Properties?.FunctionName === "vdbbench-dev-lambda-search-test"
      ) {
        // 未設定（undefined）または "Delete" であること
        expect(
          res.DeletionPolicy === undefined ||
            res.DeletionPolicy === "Delete",
        ).toBe(true);
      }
    }
  });
});
