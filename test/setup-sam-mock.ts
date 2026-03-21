import * as fs from "fs";
import * as path from "path";

/**
 * Jest globalSetup: テスト実行前に SAM ビルド出力のモックディレクトリを作成する。
 * CDK の Code.fromAsset(".aws-sam/build/VectorVerifyFunction") がスタック合成時に
 * ディレクトリの存在を要求するため、テスト用のダミーファイルを配置する。
 */
export default function setup(): void {
  const samBuildDir = path.resolve(
    ".aws-sam/build/VectorVerifyFunction",
  );
  fs.mkdirSync(samBuildDir, { recursive: true });
  fs.writeFileSync(
    path.join(samBuildDir, "handler.py"),
    "# mock handler",
  );
}
