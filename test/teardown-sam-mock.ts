import * as fs from "fs";

/**
 * Jest globalTeardown: テスト実行後に SAM ビルド出力のモックディレクトリを削除する。
 */
export default function teardown(): void {
  fs.rmSync(".aws-sam", { recursive: true, force: true });
}
