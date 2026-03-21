import * as cr from "aws-cdk-lib/custom-resources";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as opensearchserverless from "aws-cdk-lib/aws-opensearchserverless";
import { Construct } from "constructs";

export interface OpenSearchConstructProps {
  vpc: ec2.Vpc;
  vpcEndpointSg: ec2.SecurityGroup;
  lambdaRoleArn: string;
}

export class OpenSearchConstruct extends Construct {
  readonly collection: opensearchserverless.CfnCollection;
  readonly collectionEndpoint: string;

  constructor(scope: Construct, id: string, props: OpenSearchConstructProps) {
    super(scope, id);

    const collectionName = "vdbbench-dev-oss-vector";

    // OCU制限: AwsCustomResource で UpdateAccountSettings API を呼び出し
    // インデックス用・検索用それぞれ Max 2（コスト最小化）
    new cr.AwsCustomResource(this, "AccountSettings", {
      onCreate: {
        service: "OpenSearchServerless",
        action: "UpdateAccountSettings",
        parameters: {
          capacityLimits: {
            maxIndexingCapacityInOCU: 2,
            maxSearchCapacityInOCU: 2,
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of("aoss-account-settings"),
      },
      onUpdate: {
        service: "OpenSearchServerless",
        action: "UpdateAccountSettings",
        parameters: {
          capacityLimits: {
            maxIndexingCapacityInOCU: 2,
            maxSearchCapacityInOCU: 2,
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of("aoss-account-settings"),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["aoss:UpdateAccountSettings"],
          resources: ["*"],
        }),
      ]),
    });

    // 暗号化ポリシー: AWS所有キーで暗号化
    const encryptionPolicy = new opensearchserverless.CfnSecurityPolicy(
      this,
      "EncryptionPolicy",
      {
        name: `${collectionName}-enc`,
        type: "encryption",
        policy: JSON.stringify({
          Rules: [
            {
              Resource: [`collection/${collectionName}`],
              ResourceType: "collection",
            },
          ],
          AWSOwnedKey: true,
        }),
      },
    );

    // VPCエンドポイント (OpenSearch Serverless用)
    const vpcEndpoint = new opensearchserverless.CfnVpcEndpoint(
      this,
      "VpcEndpoint",
      {
        name: `${collectionName}-vpce`,
        vpcId: props.vpc.vpcId,
        subnetIds: props.vpc.selectSubnets({
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        }).subnetIds,
        securityGroupIds: [props.vpcEndpointSg.securityGroupId],
      },
    );

    // ネットワークポリシー: VPCエンドポイント経由のみ
    const networkPolicy = new opensearchserverless.CfnSecurityPolicy(
      this,
      "NetworkPolicy",
      {
        name: `${collectionName}-net`,
        type: "network",
        policy: JSON.stringify([
          {
            Rules: [
              {
                Resource: [`collection/${collectionName}`],
                ResourceType: "collection",
              },
              {
                Resource: [`collection/${collectionName}`],
                ResourceType: "dashboard",
              },
            ],
            AllowFromPublic: false,
            SourceVPCEs: [vpcEndpoint.attrId],
          },
        ]),
      },
    );

    // データアクセスポリシー: Lambda IAMロールのみ許可
    const accessPolicy = new opensearchserverless.CfnAccessPolicy(
      this,
      "DataAccessPolicy",
      {
        name: `${collectionName}-access`,
        type: "data",
        policy: JSON.stringify([
          {
            Rules: [
              {
                Resource: [`collection/${collectionName}`],
                ResourceType: "collection",
                Permission: [
                  "aoss:CreateCollectionItems",
                  "aoss:DeleteCollectionItems",
                  "aoss:UpdateCollectionItems",
                  "aoss:DescribeCollectionItems",
                ],
              },
              {
                Resource: [`index/${collectionName}/*`],
                ResourceType: "index",
                Permission: [
                  "aoss:CreateIndex",
                  "aoss:DeleteIndex",
                  "aoss:UpdateIndex",
                  "aoss:DescribeIndex",
                  "aoss:ReadDocument",
                  "aoss:WriteDocument",
                ],
              },
            ],
            Principal: [props.lambdaRoleArn],
          },
        ]),
      },
    );

    // コレクション: VECTORSEARCH タイプ（冗長スタンバイ無効でコスト最小化）
    this.collection = new opensearchserverless.CfnCollection(
      this,
      "Collection",
      {
        name: collectionName,
        type: "VECTORSEARCH",
        standbyReplicas: "DISABLED",
      },
    );

    // コレクションは暗号化・ネットワーク・アクセスポリシーに依存
    this.collection.addDependency(encryptionPolicy);
    this.collection.addDependency(networkPolicy);
    this.collection.addDependency(accessPolicy);

    this.collectionEndpoint = this.collection.attrCollectionEndpoint;
  }
}
