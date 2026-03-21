import * as cdk from "aws-cdk-lib";
import * as s3vectors from "aws-cdk-lib/aws-s3vectors";
import { Construct } from "constructs";

export interface S3VectorsConstructProps {
  // S3 VectorsはフルマネージドサービスのためVPC/SG propsは不要
  // VPCエンドポイント経由のアクセスはNetworkConstructで設定済み
}

export class S3VectorsConstruct extends Construct {
  readonly vectorBucketName: string;
  readonly indexName: string;

  constructor(
    scope: Construct,
    id: string,
    _props: S3VectorsConstructProps = {},
  ) {
    super(scope, id);

    // ベクトルバケット
    const vectorBucket = new s3vectors.CfnVectorBucket(this, "VectorBucket", {
      vectorBucketName: "vdbbench-dev-s3vectors-benchmark",
    });
    vectorBucket.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // ベクトルインデックス
    const vectorIndex = new s3vectors.CfnIndex(this, "VectorIndex", {
      vectorBucketName: vectorBucket.vectorBucketName!,
      indexName: "embeddings",
      dimension: 1536,
      distanceMetric: "cosine",
      dataType: "float32",
    });
    vectorIndex.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // 依存関係: インデックスはバケットに依存
    vectorIndex.addDependency(vectorBucket);

    this.vectorBucketName = vectorBucket.vectorBucketName!;
    this.indexName = "embeddings";
  }
}
