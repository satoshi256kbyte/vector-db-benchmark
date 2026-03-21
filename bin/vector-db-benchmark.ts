#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { VectorDbBenchmarkStack } from "../lib/vector-db-benchmark-stack";

const app = new cdk.App();

new VectorDbBenchmarkStack(app, "VectorDbBenchmarkStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});

// cdk-nag: AwsSolutionsChecks をアプリレベルで適用（全スタック対象）
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
