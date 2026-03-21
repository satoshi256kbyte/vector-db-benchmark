"""ECS Fargate 一括投入タスクのエントリポイント."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


def main() -> None:
    """メインエントリポイント（後続タスクで実装）."""
    logger.info("bulk_ingest_start")


if __name__ == "__main__":
    main()
