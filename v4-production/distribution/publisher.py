from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))

import aiohttp

from distribution.formatter import generate_daily_digest, json_to_feishu

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """单次推送的结果记录。

    Attributes:
        channel: 渠道标识，如 "feishu"。
        success: 是否成功。
        message_id: 服务端返回的消息标识。
        error: 失败时的错误描述。
    """
    channel: str
    success: bool
    message_id: str = ""
    error: str = ""


class BasePublisher(ABC):
    """推送基类，定义统一的推送接口。"""

    @abstractmethod
    async def send_message(self, article: dict) -> PublishResult:
        """推送单篇文章。

        Args:
            article: 知识条目字典。

        Returns:
            推送结果。
        """

    @abstractmethod
    async def send_digest(self, digest: dict) -> list[PublishResult]:
        """推送每日简报。

        Args:
            digest: generate_daily_digest() 返回的简报字典。

        Returns:
            每条消息的推送结果列表。
        """


class FeishuPublisher(BasePublisher):
    """飞书 Webhook 推送器。

    通过配置的 Webhook URL 发送 interactive 卡片消息。
    URL 从环境变量 FEISHU_WEBHOOK_URL 读取。
    """

    WEBHOOK_ENV: str = "FEISHU_WEBHOOK_URL"

    def __init__(self) -> None:
        self.webhook_url: str = os.environ.get(self.WEBHOOK_ENV, "").strip()
        if not self.webhook_url:
            logger.warning("FEISHU_WEBHOOK_URL 未设置，推送将跳过")

    async def send_message(self, article: dict) -> PublishResult:
        """将单篇文章转为飞书卡片并推送。

        Args:
            article: 知识条目字典。

        Returns:
            推送结果。
        """
        if not self.webhook_url:
            return PublishResult(
                channel="feishu",
                success=False,
                error="FEISHU_WEBHOOK_URL 未配置",
            )
        card = json_to_feishu(article)
        return await self._post_card(card)

    async def send_digest(self, digest: dict) -> list[PublishResult]:
        """推送简报中所有飞书卡片。

        简报中每张卡片分别发起一次 Webhook POST 请求，
        通过 asyncio.gather 并发执行。

        Args:
            digest: generate_daily_digest() 返回的简报字典。

        Returns:
            每张卡片的推送结果列表。
        """
        cards: list[dict[str, Any]] = digest.get("feishu", [])
        if not cards:
            logger.info("飞书简报为空，跳过推送")
            return [
                PublishResult(
                    channel="feishu",
                    success=True,
                    message_id="skipped-empty",
                ),
            ]

        if not self.webhook_url:
            return [
                PublishResult(
                    channel="feishu",
                    success=False,
                    error="FEISHU_WEBHOOK_URL 未配置",
                ),
            ]

        results = await asyncio.gather(
            *[self._post_card(c) for c in cards],
            return_exceptions=True,
        )

        publish_results: list[PublishResult] = []
        for i, r in enumerate(results):
            if isinstance(r, PublishResult):
                publish_results.append(r)
            elif isinstance(r, Exception):
                publish_results.append(
                    PublishResult(
                        channel="feishu",
                        success=False,
                        error=str(r),
                    ),
                )
            else:
                publish_results.append(
                    PublishResult(
                        channel="feishu",
                        success=False,
                        error=f"未知返回类型: {type(r)}",
                    ),
                )

        success_count = sum(1 for r in publish_results if r.success)
        logger.info(
            "飞书推送完成: %d/%d 成功",
            success_count,
            len(publish_results),
        )
        return publish_results

    async def _post_card(self, card: dict[str, Any]) -> PublishResult:
        """向飞书 Webhook 发送单张卡片。

        Args:
            card: json_to_feishu() 返回的完整消息体。

        Returns:
            推送结果。
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=card,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body: str = await resp.text()
                    if resp.status == 200:
                        return PublishResult(
                            channel="feishu",
                            success=True,
                            message_id=str(resp.status),
                        )
                    return PublishResult(
                        channel="feishu",
                        success=False,
                        error=f"HTTP {resp.status}: {body[:200]}",
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return PublishResult(
                channel="feishu",
                success=False,
                error=str(e),
            )


async def publish_daily_digest(
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
) -> list[PublishResult]:
    """统一异步入口：生成当日简报并推送到所有已配置渠道。

    流程：
        1. 调用 generate_daily_digest() 生成 Markdown / 飞书卡片内容。
        2. 无文章时记录日志并跳过。
        3. 有文章时通过 FeishuPublisher 并发推送所有卡片。

    Args:
        knowledge_dir: 文章目录路径，默认 "knowledge/articles"。
        date: 日期 "YYYY-MM-DD"，默认今天。
        top_n: 简报包含的条目数上限，默认 5。

    Returns:
        各渠道推送结果列表。
    """
    digest: dict = generate_daily_digest(
        knowledge_dir=knowledge_dir,
        date=date,
        top_n=top_n,
    )

    if not digest.get("feishu"):
        logger.info("今日无文章，跳过推送")
        return [
            PublishResult(
                channel="feishu",
                success=True,
                message_id="skipped-empty",
            ),
        ]

    publisher = FeishuPublisher()
    return await publisher.send_digest(digest)
