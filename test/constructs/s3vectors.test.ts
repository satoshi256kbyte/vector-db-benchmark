import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { S3VectorsConstruct } from "../../lib/constructs/s3vectors";

describe("S3VectorsConstruct", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    new S3VectorsConstruct(stack, "S3Vectors");
    template = Template.fromStack(stack);
  });

  test("CfnVectorBucket が作成される", () => {
    template.hasResourceProperties("AWS::S3Vectors::VectorBucket", {
      VectorBucketName: "awsprivatelab-dev-s3vectors-benchmark",
    });
  });

  test("CfnIndex が dimension: 1536, distanceMetric: cosine, dataType: float32 で作成される", () => {
    template.hasResourceProperties("AWS::S3Vectors::Index", {
      IndexName: "embeddings",
      Dimension: 1536,
      DistanceMetric: "cosine",
      DataType: "float32",
    });
  });

  test("VectorBucket の DeletionPolicy が Delete である", () => {
    template.hasResource("AWS::S3Vectors::VectorBucket", {
      DeletionPolicy: "Delete",
    });
  });

  test("VectorIndex の DeletionPolicy が Delete である", () => {
    template.hasResource("AWS::S3Vectors::Index", {
      DeletionPolicy: "Delete",
    });
  });

  test("VectorIndex が VectorBucket に依存している", () => {
    const bucketLogicalIds = Object.entries(
      template.toJSON().Resources,
    )
      .filter(([, v]) => (v as Record<string, string>).Type === "AWS::S3Vectors::VectorBucket")
      .map(([k]) => k);

    template.hasResource("AWS::S3Vectors::Index", {
      DependsOn: bucketLogicalIds,
    });
  });
});
