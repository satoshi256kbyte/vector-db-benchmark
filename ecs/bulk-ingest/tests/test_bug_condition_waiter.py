"""バグ条件探索テスト: ECS Waiter タイムアウトと S3 Vectors バッチサイズ過小.

**Property 1: Bug Condition** - ECS Waiter タイムアウトと S3 Vectors バッチサイズ過小

**Validates: Requirements 1.1, 1.2, 1.3**

未修正コードではこのテストは失敗する（バグの存在を証明する）。
修正後は batch_size=200 に変更され、テストが成功する。

テスト内容:
- S3VectorsIngester.ingest_all() のデフォルト batch_size が 200 であること（修正後の期待値）
- 大量レコード投入時に API コール回数が適切であること
- isBugCondition_BatchSize: batch_size == 50 AND record_count >= 100000 → 過大な API コール
"""

from __future__ import annotations

import inspect
import math

from hypothesis import given, settings
from hypothesis import strategies as st

from ingestion import S3VectorsIngester


# ===========================================================================
# テスト 1: S3VectorsIngester.ingest_all() のデフォルト batch_size が 200 であること
# ===========================================================================


class TestS3VectorsDefaultBatchSize:
    """S3VectorsIngester.ingest_all() のデフォルト batch_size 検証.

    **Validates: Requirements 1.3**

    未修正コードでは batch_size=50 のため失敗する。
    修正後は batch_size=200 に変更され、テストが成功する。
    """

    def test_default_batch_size_is_200(self) -> None:
        """ingest_all() のデフォルト batch_size が 200 であること."""
        sig = inspect.signature(S3VectorsIngester.ingest_all)
        batch_size_param = sig.parameters["batch_size"]
        assert batch_size_param.default == 200, (
            f"S3VectorsIngester.ingest_all() のデフォルト batch_size は 200 であるべき"
            f"（実際: {batch_size_param.default}）。"
            f"batch_size=50 では 100,000 件投入に 2,000 回の API コールが必要となり、"
            f"処理時間が 10 分を大幅に超過する。"
        )


# ===========================================================================
# テスト 2: Hypothesis - 大量レコード投入時の API コール回数検証
# ===========================================================================


class TestExcessiveApiCalls:
    """大量レコード投入時の API コール回数が適切であること.

    **Validates: Requirements 1.3**

    batch_size=50 で record_count >= 100,000 の場合、
    API コール回数が ceil(record_count / 50) = 2,000+ 回になる。
    修正後は batch_size=200 で API コール回数が 1/4 に削減される。
    """

    @given(record_count=st.integers(min_value=100000, max_value=500000))
    @settings(max_examples=20, deadline=None)
    def test_api_call_count_with_default_batch_size(self, record_count: int) -> None:
        """デフォルト batch_size での API コール回数が 1000 回以下であること.

        **Validates: Requirements 1.3**

        修正後の batch_size=200 では、100,000 件で 500 回、500,000 件で 2,500 回。
        未修正の batch_size=50 では、100,000 件で 2,000 回となり、このテストは失敗する。

        Args:
            record_count: 投入レコード数（100,000 以上）
        """
        sig = inspect.signature(S3VectorsIngester.ingest_all)
        default_batch_size = sig.parameters["batch_size"].default

        api_call_count = math.ceil(record_count / default_batch_size)

        # batch_size=200 の場合: 100,000件 → 500回、500,000件 → 2,500回
        # batch_size=50 の場合: 100,000件 → 2,000回（この閾値で失敗する）
        max_acceptable_calls = math.ceil(record_count / 200)
        assert api_call_count <= max_acceptable_calls, (
            f"API コール回数が過大: record_count={record_count}, "
            f"batch_size={default_batch_size}, api_calls={api_call_count}, "
            f"max_acceptable={max_acceptable_calls}。"
            f"batch_size を 200 以上に増加させる必要がある。"
        )


# ===========================================================================
# テスト 3: isBugCondition_BatchSize の検証
# ===========================================================================


class TestIsBugConditionBatchSize:
    """isBugCondition_BatchSize: batch_size == 50 AND record_count >= 100000 → 過大な API コール.

    **Validates: Requirements 1.3**

    未修正コードでは batch_size=50 のためバグ条件が成立し、テストが失敗する。
    修正後は batch_size=200 のためバグ条件が成立せず、テストが成功する。
    """

    @given(record_count=st.integers(min_value=100000, max_value=1000000))
    @settings(max_examples=20, deadline=None)
    def test_bug_condition_not_met_with_fixed_batch_size(self, record_count: int) -> None:
        """修正後のデフォルト batch_size ではバグ条件が成立しないこと.

        **Validates: Requirements 1.3**

        isBugCondition_BatchSize:
          batch_size == 50 AND record_count >= 100000 → True（バグあり）
          batch_size != 50 → False（バグなし）

        Args:
            record_count: 投入レコード数（100,000 以上）
        """
        sig = inspect.signature(S3VectorsIngester.ingest_all)
        default_batch_size = sig.parameters["batch_size"].default

        is_bug_condition = (default_batch_size == 50) and (record_count >= 100000)

        assert not is_bug_condition, (
            f"バグ条件が成立: batch_size={default_batch_size}, record_count={record_count}。"
            f"S3VectorsIngester.ingest_all() の batch_size=50 では "
            f"{math.ceil(record_count / 50)} 回の API コールが必要。"
            f"batch_size を 200 に増加させてバグ条件を解消する必要がある。"
        )
