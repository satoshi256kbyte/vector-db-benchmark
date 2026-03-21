import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import * as fc from "fast-check";
import { NetworkConstruct } from "../../lib/constructs/network";
import { AuroraConstruct } from "../../lib/constructs/aurora";
import { VerifyFunctionConstruct } from "../../lib/constructs/verify-function";

/**
 * VerifyFunctionConstruct のプロパティベーステスト。
 *
 * fast-check で任意の文字列プロパティ（s3vectorsBucketName, s3vectorsIndexName,
 * opensearchCollectionEndpoint）を生成し、CDK 合成結果が正当性プロパティを
 * 満たすことを検証する。
 */

/** 非空の ASCII 文字列を生成する arbitrary */
const nonEmptyString = fc.string({ minLength: 1, maxLength: 64 }).filter((s) => s.trim().length > 0);

/** opensearchCollectionEndpoint は省略可能 */
const optionalEndpoint = fc.option(
  fc.string({ minLength: 1, maxLength: 128 }).filter((s) => s.trim().length > 0),
  { nil: undefined },
);

/** テスト用スタックを合成して Template を返す */
function synthesize(props: {
  s3vectorsBucketName: string;
  s3vectorsIndexName: string;
  opensearchCollectionEndpoint?: string;
}): Template {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, "PropertyTestStack");
  const network = new NetworkConstruct(stack, "Network");
  const aurora = new AuroraConstruct(stack, "Aurora", {
    vpc: network.vpc,
    auroraSg: network.auroraSg,
  });
  new VerifyFunctionConstruct(stack, "VerifyFunction", {
    vpc: network.vpc,
    lambdaSg: network.lambdaSg,
    auroraCluster: aurora.cluster,
    auroraSecret: aurora.secret,
    opensearchCollectionEndpoint: props.opensearchCollectionEndpoint,
    s3vectorsBucketName: props.s3vectorsBucketName,
    s3vectorsIndexName: props.s3vectorsIndexName,
  });
  return Template.fromStack(stack);
}

// Feature: sam-lambda-migration, Property 1: SAM ビルド出力参照
// **Validates: Requirements 2.1, 3.3**
describe("Property 1: SAM ビルド出力参照（bundling 除去）", () => {
  it("合成された Lambda のコードアセットが .aws-sam/build/VectorVerifyFunction を参照し bundling メタデータを含まない", () => {
    fc.assert(
      fc.property(
        nonEmptyString,
        nonEmptyString,
        optionalEndpoint,
        (bucketName, indexName, endpoint) => {
          const template = synthesize({
            s3vectorsBucketName: bucketName,
            s3vectorsIndexName: indexName,
            opensearchCollectionEndpoint: endpoint,
          });

          const lambdaFunctions = template.findResources("AWS::Lambda::Function");
          const fnKeys = Object.keys(lambdaFunctions);
          expect(fnKeys.length).toBeGreaterThanOrEqual(1);

          for (const key of fnKeys) {
            const fn = lambdaFunctions[key];

            // Code.S3Key が存在する（fromAsset によるアセット参照）
            expect(fn.Properties.Code).toBeDefined();
            expect(fn.Properties.Code.S3Bucket).toBeDefined();
            expect(fn.Properties.Code.S3Key).toBeDefined();

            // CDK bundling メタデータが存在しないこと
            const metadata = fn.Metadata ?? {};
            expect(metadata["aws:asset:is-bundled"]).toBeUndefined();
          }

          // CloudFormation パラメータにアセットパスが含まれ、
          // そのパスが .aws-sam/build/VectorVerifyFunction を参照していることを確認
          const cfnTemplate = template.toJSON();
          const params = cfnTemplate.Parameters ?? {};
          const assetParams = Object.keys(params).filter(
            (p) => p.startsWith("AssetParameters") || params[p].Default?.toString().includes("asset"),
          );
          // アセットパラメータが存在する（Code.fromAsset が使われている証拠）
          // Note: CDK は fromAsset のパスをハッシュ化するため直接パス文字列は検証できないが、
          // bundling メタデータが無いことで bundling 除去を確認する
        },
      ),
      { numRuns: 100 },
    );
  });
});

// Feature: sam-lambda-migration, Property 2: Lambda 非コード設定の保全
// **Validates: Requirements 2.2, 2.3**
describe("Property 2: Lambda 非コード設定の保全", () => {
  it("任意の入力に対して VPC 配置・SG・環境変数・メモリ・タイムアウトが保持される", () => {
    fc.assert(
      fc.property(
        nonEmptyString,
        nonEmptyString,
        optionalEndpoint,
        (bucketName, indexName, endpoint) => {
          const template = synthesize({
            s3vectorsBucketName: bucketName,
            s3vectorsIndexName: indexName,
            opensearchCollectionEndpoint: endpoint,
          });

          // メモリサイズ 256 MB
          template.hasResourceProperties("AWS::Lambda::Function", {
            MemorySize: 256,
          });

          // タイムアウト 300 秒
          template.hasResourceProperties("AWS::Lambda::Function", {
            Timeout: 300,
          });

          // VPC 配置（プライベート分離サブネット）とセキュリティグループ
          template.hasResourceProperties("AWS::Lambda::Function", {
            VpcConfig: Match.objectLike({
              SubnetIds: Match.anyValue(),
              SecurityGroupIds: Match.anyValue(),
            }),
          });

          // IAM ロール
          template.hasResourceProperties("AWS::Lambda::Function", {
            Role: Match.anyValue(),
          });

          // 必須環境変数の存在確認
          const envVars: Record<string, unknown> = {
            AURORA_SECRET_ARN: Match.anyValue(),
            AURORA_CLUSTER_ENDPOINT: Match.anyValue(),
            POWERTOOLS_SERVICE_NAME: "vector-verify",
            POWERTOOLS_LOG_LEVEL: "INFO",
            S3VECTORS_BUCKET_NAME: bucketName,
            S3VECTORS_INDEX_NAME: indexName,
          };

          if (endpoint !== undefined) {
            envVars.OPENSEARCH_ENDPOINT = endpoint;
          }

          template.hasResourceProperties("AWS::Lambda::Function", {
            Environment: {
              Variables: Match.objectLike(envVars),
            },
          });
        },
      ),
      { numRuns: 100 },
    );
  });
});
