# ECS Waiter タイムアウト修正 設計ドキュメント

## 概要

ベンチマークスクリプト (`scripts/benchmark.sh`) で S3 Vectors に 100,000 件のデータを投入する ECS タスクが、`aws ecs wait tasks-stopped` のデフォルトタイムアウト（約10分）を超過して失敗する。

根本原因は2つある:

1. **シェルスクリプト側**: `aws ecs wait tasks-stopped` のデフォルト設定（100回ポーリング × 6秒間隔 ≈ 10分）では、大量データ投入タスクの完了を待機しきれない
2. **Python 側**: `S3VectorsIngester.ingest_all()` のデフォルトバッチサイズが 50 件と小さく、100,000 件投入に 2,000 回の PutVectors API コールが必要となり処理時間が長大化する

修正方針は、シェルスクリプト側の waiter をカスタムポーリングループに置き換えて待機時間を十分に確保し、Python 側のバッチサイズを増加させて API コール回数を削減する。

## 用語集

- **Bug_Condition (C)**: ECS タスクの実行時間が `aws ecs wait tasks-stopped` のデフォルトタイムアウト（約10分）を超過する条件
- **Property (P)**: タイムアウトに関わらず ECS タスクの完了を正しく待機し、成功/失敗を正確に検出する動作
- **Preservation**: 修正によって変更されてはならない既存動作。Aurora/OpenSearch のバッチサイズ、ECS タスク起動パラメータ、結果 JSON フォーマット等
- **`run_ecs_task()`**: `scripts/benchmark.sh` のデータ投入用 ECS タスク起動・待機関数
- **`run_ecs_task_with_mode()`**: `scripts/benchmark.sh` のモード指定 ECS タスク起動・待機関数（index_drop, index_create, count）
- **`S3VectorsIngester`**: `ecs/bulk-ingest/ingestion.py` の S3 Vectors データ投入クラス
- **PutVectors API**: S3 Vectors のベクトルデータ投入 API（1回あたり最大500件、ペイロード最大20MiB）

## バグ詳細

### バグ条件

2つの関連するバグ条件が存在する:

**バグ 1: ECS Waiter タイムアウト**

`run_ecs_task()` または `run_ecs_task_with_mode()` で起動した ECS タスクの実行時間が約10分を超過すると、`aws ecs wait tasks-stopped` がデフォルトタイムアウト（100回 × 6秒 = 600秒）で `Waiter TasksStopped failed: Max attempts exceeded` エラーを返す。

**形式仕様:**
```
FUNCTION isBugCondition_Waiter(input)
  INPUT: input of type ECSTaskExecution {target_db, task_mode, record_count}
  OUTPUT: boolean

  estimated_duration := estimateTaskDuration(input.target_db, input.task_mode, input.record_count)
  waiter_timeout := 100 * 6  // デフォルト: 100回ポーリング × 6秒間隔 = 600秒

  RETURN estimated_duration > waiter_timeout
END FUNCTION
```

**バグ 2: S3 Vectors バッチサイズ過小**

`S3VectorsIngester.ingest_all()` のデフォルトバッチサイズが 50 件のため、100,000 件投入に 2,000 回の PutVectors API コールが必要。各 API コールのネットワークレイテンシが累積し、処理時間が 10 分を大幅に超過する。Aurora（batch_size=500、200回）や OpenSearch（batch_size=1000、100回）と比較して API コール回数が桁違いに多い。

**形式仕様:**
```
FUNCTION isBugCondition_BatchSize(input)
  INPUT: input of type S3VectorsIngestion {record_count, batch_size}
  OUTPUT: boolean

  api_call_count := CEIL(input.record_count / input.batch_size)
  estimated_duration := api_call_count * AVG_API_LATENCY_SECONDS

  RETURN input.batch_size == 50
         AND input.record_count >= 100000
         AND estimated_duration > 600  // 10分超過
END FUNCTION
```

### 具体例

- 例1: S3 Vectors に 100,000 件投入（batch_size=50）→ 2,000 回の API コール → 約20-30分 → `aws ecs wait tasks-stopped` が10分でタイムアウト → ベンチマーク失敗
- 例2: Aurora に 100,000 件投入（batch_size=500）→ 200 回の API コール → 約5分 → waiter 内で正常完了 → 成功
- 例3: OpenSearch に 100,000 件投入（batch_size=1000）→ 100 回の API コール → 約3分 → waiter 内で正常完了 → 成功
- 例4: S3 Vectors に 100,000 件投入（batch_size=200）→ 500 回の API コール → 約5-10分 → waiter タイムアウトの境界ケース

## 期待される動作

### 保持要件

**変更されない動作:**
- `AuroraIngester.ingest_all()` のデフォルト batch_size=500 は変更しない
- `OpenSearchIngester.ingest_all()` のデフォルト batch_size=1000 は変更しない
- ECS タスクの起動パラメータ（コンテナオーバーライド、ネットワーク設定等）は変更しない
- 結果 JSON のフォーマットおよび保存先は変更しない
- `run_ecs_task()` / `run_ecs_task_with_mode()` の戻り値（成功時 0、失敗時 1）は変更しない
- ECS タスクが実際にエラーで失敗した場合の検出・報告動作は維持する
- `S3VectorsIngester.ingest_batch()` の PutVectors API 呼び出しフォーマットは変更しない
- `S3VectorsIngester.ingest_all()` の batch_size 上限チェック（500件）は維持する

**スコープ:**
ECS タスクの待機方法と S3 Vectors のバッチサイズのみを変更する。それ以外の全ての動作（タスク起動、ログ収集、メトリクス取得、コスト算出、結果 JSON 生成等）は影響を受けない。

## 仮説的根本原因

バグの根本原因は以下の2点:

1. **`aws ecs wait tasks-stopped` のデフォルト制限**: AWS CLI の waiter はデフォルトで最大100回のポーリング（6秒間隔）を行い、約10分でタイムアウトする。この制限はカスタマイズ不可（CLI オプションなし）のため、長時間タスクには不適切。

2. **S3 Vectors バッチサイズの保守的設定**: `S3VectorsIngester.ingest_all()` のデフォルト batch_size=50 は、PutVectors API のペイロードサイズ制限（20MiB）を考慮した保守的な値。しかし 1536 次元 float32 ベクトル（約6KB/件）の場合、200件でも約1.3MB 程度であり、API 制限の範囲内で大幅に増加可能。

3. **2つの原因の相乗効果**: バッチサイズが小さいことで処理時間が長くなり、waiter のタイムアウトに引っかかる。どちらか一方の修正でも改善するが、両方修正することで確実にタイムアウトを回避できる。

## 正確性プロパティ

Property 1: Bug Condition - ECS タスク待機のタイムアウト耐性

_For any_ ECS タスク実行において、タスクの実行時間が10分を超過する場合でも、カスタムポーリングループが最大60分（MAX_WAIT_SECONDS=3600、POLL_INTERVAL=30）まで待機し、タスクが正常終了すれば成功を返し、異常終了すれば失敗を正しく検出する。

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition - S3 Vectors バッチサイズ増加による処理時間短縮

_For any_ S3 Vectors への大量データ投入（100,000件以上）において、バッチサイズを 50 から 200 に増加させることで API コール回数が 1/4 に削減され、処理時間が大幅に短縮される。

**Validates: Requirements 2.3**

Property 3: Preservation - 既存 DB のバッチサイズ不変

_For any_ Aurora または OpenSearch へのデータ投入において、`AuroraIngester.ingest_all()` の batch_size=500 および `OpenSearchIngester.ingest_all()` の batch_size=1000 は変更されず、従来通りの動作を維持する。

**Validates: Requirements 3.1, 3.2, 3.6, 3.7**

Property 4: Preservation - ECS タスク失敗検出の維持

_For any_ ECS タスクが実際にエラーで失敗した場合（終了コード != 0）、カスタムポーリングループは待機時間の延長に関わらずタスク失敗を正しく検出し、エラーを報告する。

**Validates: Requirements 3.3, 3.4, 3.8**

## 修正実装

### 変更内容

根本原因分析に基づき、以下の変更を行う:

**ファイル**: `scripts/benchmark.sh`

**関数**: `run_ecs_task()`, `run_ecs_task_with_mode()`

**具体的な変更**:
1. **waiter 置き換え**: `aws ecs wait tasks-stopped` をカスタムポーリングループに置き換える
   - `MAX_WAIT_SECONDS=3600`（最大60分待機）
   - `POLL_INTERVAL=30`（30秒間隔でポーリング）
   - `aws ecs describe-tasks` で `lastStatus` を確認し、`STOPPED` になるまでループ
2. **タイムアウト処理**: 最大待機時間を超過した場合はエラーメッセージを出力して失敗を返す
3. **進捗ログ**: ポーリングごとに経過時間とタスクステータスをログ出力する

**ファイル**: `ecs/bulk-ingest/ingestion.py`

**クラス**: `S3VectorsIngester`

**具体的な変更**:
1. **バッチサイズ増加**: `ingest_all()` のデフォルト `batch_size` を 50 から 200 に変更
2. **docstring 更新**: バッチサイズ変更の理由を docstring に反映

## テスト戦略

### 検証アプローチ

テスト戦略は2段階で進める: まず未修正コードでバグを再現する探索テストを実行し、次に修正後のコードで修正確認と保持確認を行う。

### 探索的バグ条件チェック

**目的**: 修正実装前にバグを再現するカウンターサンプルを発見し、根本原因分析を確認または反証する。

**テスト計画**: シェルスクリプトの waiter 動作と Python のバッチサイズ設定をテストする。未修正コードで実行して失敗を観察し、根本原因を理解する。

**テストケース**:
1. **Waiter タイムアウトテスト**: `aws ecs wait tasks-stopped` のデフォルト設定で10分超のタスクを待機（未修正コードで失敗する）
2. **S3 Vectors バッチサイズテスト**: `S3VectorsIngester.ingest_all()` のデフォルト batch_size=50 で API コール回数を確認（未修正コードで過大な回数になる）
3. **API コール回数比較テスト**: 3つの DB の API コール回数を比較し、S3 Vectors のみ桁違いに多いことを確認（未修正コードで失敗する）

**期待されるカウンターサンプル**:
- S3 Vectors の 100,000 件投入で 2,000 回の API コールが発生
- 処理時間が 10 分を超過し waiter がタイムアウト

### 修正確認チェック

**目的**: バグ条件が成立する全ての入力に対して、修正後の関数が期待される動作を生成することを検証する。

**擬似コード:**
```
FOR ALL input WHERE isBugCondition_Waiter(input) DO
  result := run_ecs_task_fixed(input)
  ASSERT taskCompletionDetected(result)
  ASSERT correctExitCodeReported(result)
END FOR

FOR ALL input WHERE isBugCondition_BatchSize(input) DO
  api_calls := countApiCalls(ingest_all_fixed(input))
  ASSERT api_calls <= CEIL(input.record_count / 200)
END FOR
```

### 保持確認チェック

**目的**: バグ条件が成立しない全ての入力に対して、修正後の関数が元の関数と同じ結果を生成することを検証する。

**擬似コード:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT run_ecs_task_original(input) = run_ecs_task_fixed(input)
  ASSERT ingest_all_original(input) = ingest_all_fixed(input)
END FOR
```

**テストアプローチ**: プロパティベーステストを保持確認に推奨する。理由:
- 入力ドメイン全体にわたって多数のテストケースを自動生成できる
- 手動ユニットテストでは見逃しがちなエッジケースを検出できる
- 非バグ入力に対する動作不変の強い保証を提供する

**テスト計画**: まず未修正コードで Aurora/OpenSearch のデータ投入やマウスクリック等の動作を観察し、その動作を捕捉するプロパティベーステストを記述する。

**テストケース**:
1. **Aurora バッチサイズ保持**: `AuroraIngester.ingest_all()` の batch_size=500 が変更されていないことを検証
2. **OpenSearch バッチサイズ保持**: `OpenSearchIngester.ingest_all()` の batch_size=1000 が変更されていないことを検証
3. **ECS タスク起動パラメータ保持**: タスク起動時のコンテナオーバーライドやネットワーク設定が変更されていないことを検証
4. **タスク失敗検出保持**: ECS タスクが異常終了した場合のエラー検出・報告が正しく動作することを検証

### ユニットテスト

- `S3VectorsIngester.ingest_all()` のデフォルト batch_size が 200 であることを確認
- `S3VectorsIngester.ingest_all()` の batch_size 上限チェック（500件）が維持されていることを確認
- カスタムポーリングループのタイムアウト処理をテスト（BATS テスト）
- カスタムポーリングループの正常完了検出をテスト（BATS テスト）

### プロパティベーステスト

- ランダムな record_count と batch_size の組み合わせで `S3VectorsIngester.ingest_all()` の API コール回数が正しいことを検証
- ランダムな入力で `AuroraIngester` / `OpenSearchIngester` のバッチサイズが不変であることを検証
- ランダムな ECS タスク実行時間でカスタムポーリングループが正しく動作することを検証

### 統合テスト

- ベンチマークスクリプト全体の実行フローで S3 Vectors のデータ投入が成功することを確認
- 3つの DB 全てのベンチマークサイクルが正常に完了することを確認
- ECS タスク失敗時のエラーハンドリングが正しく動作することを確認
