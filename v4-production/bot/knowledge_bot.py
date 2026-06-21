from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))

logger = logging.getLogger(__name__)

# ====================================================================
#  枚举
# ====================================================================


class Intent(Enum):
    """用户意图枚举。"""
    SEARCH = "search"
    TODAY = "today"
    TOP = "top"
    RECOMMEND = "recommend"
    SUBSCRIBE = "subscribe"
    HELP = "help"
    UNKNOWN = "unknown"


class Permission(Enum):
    """权限等级枚举，等级值越大权限越高。"""
    READ = 1
    WRITE = 2
    DELETE = 3


# ====================================================================
#  数据类
# ====================================================================


@dataclass
class BotResponse:
    """Bot 响应，包含文本回显和可选飞书卡片列表。

    Attributes:
        text: Markdown 格式的回显文本。
        feishu_cards: 飞书 interactive 卡片列表，可为空。
    """
    text: str
    feishu_cards: list[dict[str, Any]] = field(default_factory=list)


# ====================================================================
#  意图识别
# ====================================================================


def recognize_intent(text: str) -> tuple[Intent, str]:
    """通过规则匹配识别用户意图，不使用 LLM。

    匹配优先级：
        1. 命令前缀（/search, /today, /top, /subscribe, /help）
        2. 自然语言关键词

    Args:
        text: 用户输入文本。

    Returns:
        (Intent, 参数字符串)。
    """
    text = text.strip()

    # ── 命令前缀匹配 ──
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        params = parts[1] if len(parts) > 1 else ""

        command_map: dict[str, Intent] = {
            "/search": Intent.SEARCH,
            "/today": Intent.TODAY,
            "/top": Intent.TOP,
            "/recommend": Intent.RECOMMEND,
            "/subscribe": Intent.SUBSCRIBE,
            "/help": Intent.HELP,
        }

        matched = command_map.get(cmd)
        if matched:
            return matched, params

    # ── 自然语言匹配 ──
    nl_rules: list[tuple[list[str], Intent]] = [
        (["搜索", "查询", "查找", "找"], Intent.SEARCH),
        (["今天", "今日", "简报"], Intent.TODAY),
        (["热门", "排行", "top"], Intent.TOP),
        (["推荐", "高分", "评分最高", "最值得", "最有价值"], Intent.RECOMMEND),
        (["订阅", "关注"], Intent.SUBSCRIBE),
        (["帮助", "help", "功能", "命令"], Intent.HELP),
    ]

    text_lower = text.lower()
    for keywords, intent in nl_rules:
        for kw in keywords:
            if kw in text_lower or kw in text:
                # 对 SEARCH 提取关键词后的部分作为参数
                if intent == Intent.SEARCH:
                    idx = text.find(kw)
                    params = text[idx + len(kw):].strip()
                    # 去除标点前缀
                    params = re.sub(r"^[：:，,。.\s]+", "", params)
                    return intent, params
                return intent, ""

    return Intent.UNKNOWN, text


# ====================================================================
#  搜索引擎
# ====================================================================


class KnowledgeSearchEngine:
    """知识库搜索引擎。

    基于 index.json 进行关键词/标签/日期匹配，
    匹配结果从 articles 目录加载完整文章。
    """

    def __init__(
        self,
        articles_dir: str = "knowledge/articles",
        index_path: str | None = None,
    ) -> None:
        self.articles_dir: str = articles_dir
        self.index_path: str = index_path or os.path.join(
            articles_dir, "index.json",
        )
        self._index: list[dict[str, Any]] | None = None

    def _load_index(self) -> list[dict[str, Any]]:
        if self._index is not None:
            return self._index
        try:
            with open(self.index_path, encoding="utf-8") as f:
                self._index = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning("加载索引失败 %s: %s", self.index_path, e)
            self._index = []
        return self._index

    def _load_article(self, article_id: str) -> dict[str, Any] | None:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", article_id)
        filepath = os.path.join(self.articles_dir, f"{safe_name}.json")
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            logger.warning("加载文章失败 %s: %s", filepath, e)
            return None

    def search(
        self,
        keyword: str = "",
        tags: list[str] | None = None,
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        """按关键词和/或标签搜索文章。

        Args:
            keyword: 标题关键词（不区分大小写），为空时不按关键词过滤。
            tags: 标签列表（取交集匹配），为空时不按标签过滤。
            top_n: 最大返回条数，默认 10。

        Returns:
            匹配的完整文章列表，按 index 顺序排列。
        """
        index = self._load_index()
        articles: list[dict[str, Any]] = []

        for entry in index:
            if keyword:
                title = entry.get("title", "")
                if keyword.lower() not in title.lower():
                    continue

            if tags:
                entry_tags = set(entry.get("tags", []))
                if not entry_tags.intersection(tags):
                    continue

            full = self._load_article(entry["id"])
            if full:
                articles.append(full)
                if len(articles) >= top_n:
                    break

        return articles

    def get_by_date(
        self,
        date: str,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """获取指定日期的文章。

        Args:
            date: 日期字符串 "YYYY-MM-DD"。
            top_n: 最大返回条数，默认 5。

        Returns:
            该日期的文章列表，按 index 顺序排列。
        """
        date_fmt = date.replace("-", "")
        index = self._load_index()

        matched = [e for e in index if e["id"].startswith(date_fmt)]

        articles: list[dict[str, Any]] = []
        for entry in matched[:top_n]:
            full = self._load_article(entry["id"])
            if full:
                articles.append(full)

        return articles

    def get_top(self, top_n: int = 5) -> list[dict[str, Any]]:
        """获取今日热门文章，按 star 数降序排列。

        Args:
            top_n: 最大返回条数，默认 5。

        Returns:
            今日文章按热度排序的列表。
        """
        today = datetime.now().strftime("%Y%m%d")
        index = self._load_index()

        matched = [e for e in index if e["id"].startswith(today)]

        articles: list[dict[str, Any]] = []
        for entry in matched:
            full = self._load_article(entry["id"])
            if full:
                articles.append(full)

        articles.sort(
            key=lambda a: (a.get("maturity") or {}).get("stars", 0),
            reverse=True,
        )
        return articles[:top_n]


# ====================================================================
#  订阅管理
# ====================================================================


class SubscriptionManager:
    """用户订阅管理器。

    订阅数据持久化到 JSON 文件。
    subscribe/unsubscribe 为 Toggle 开关。
    """

    def __init__(self, path: str = "data/subscriptions.json") -> None:
        self.path: str = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("保存订阅失败 %s: %s", self.path, e)

    def subscribe(self, user_id: str) -> bool:
        """Toggle 订阅开关。

        Args:
            user_id: 用户标识。

        Returns:
            True 表示已订阅，False 表示已取消订阅。
        """
        if user_id in self._data:
            del self._data[user_id]
            self._save()
            return False
        self._data[user_id] = {
            "user_id": user_id,
            "subscribed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save()
        return True

    def is_subscribed(self, user_id: str) -> bool:
        """检查用户是否已订阅。

        Args:
            user_id: 用户标识。

        Returns:
            是否已订阅。
        """
        return user_id in self._data

    def list_all(self) -> list[dict[str, Any]]:
        """获取所有订阅用户列表。

        Returns:
            订阅用户信息列表。
        """
        return list(self._data.values())


# ====================================================================
#  权限管理
# ====================================================================


class PermissionManager:
    """三级权限管理器。

    权限等级：READ(1) < WRITE(2) < DELETE(3)。
    未在配置中的用户默认 READ 权限。
    数据持久化到 JSON 文件。
    """

    def __init__(
        self,
        path: str = "data/permissions.json",
        admin_ids: list[str] | None = None,
    ) -> None:
        self.path: str = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._data: dict[str, int] = self._load()

        if admin_ids:
            for uid in admin_ids:
                self._data[uid] = Permission.DELETE.value
            self._save()

    def _load(self) -> dict[str, int]:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
                return {k: int(v) for k, v in raw.items()}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("保存权限失败 %s: %s", self.path, e)

    def set(self, user_id: str, permission: Permission) -> None:
        """设置用户权限。

        Args:
            user_id: 用户标识。
            permission: 目标权限等级。
        """
        self._data[user_id] = permission.value
        self._save()

    def get(self, user_id: str) -> Permission:
        """获取用户当前权限等级。

        Args:
            user_id: 用户标识。

        Returns:
            用户的权限等级，未配置则返回 READ。
        """
        val = self._data.get(user_id, Permission.READ.value)
        return Permission(val)

    def check(self, user_id: str, required: Permission) -> bool:
        """检查用户是否满足指定权限。

        满足条件：用户权限等级 >= 要求权限等级。

        Args:
            user_id: 用户标识。
            required: 所需的最低权限等级。

        Returns:
            是否满足权限要求。
        """
        return self.get(user_id).value >= required.value


# ====================================================================
#  意图与权限映射
# ====================================================================

_INTENT_PERMISSIONS: dict[Intent, Permission] = {
    Intent.SEARCH: Permission.READ,
    Intent.TODAY: Permission.READ,
    Intent.TOP: Permission.READ,
    Intent.RECOMMEND: Permission.READ,
    Intent.SUBSCRIBE: Permission.WRITE,
    Intent.HELP: Permission.READ,
    Intent.UNKNOWN: Permission.READ,
}


# ====================================================================
#  Bot 主类
# ====================================================================


class KnowledgeBot:
    """知识库 Bot 主入口。

    整合搜索引擎、订阅管理、权限控制，
    对外提供统一的 handle_message 接口。
    """

    def __init__(
        self,
        search_engine: KnowledgeSearchEngine | None = None,
        subscription_mgr: SubscriptionManager | None = None,
        permission_mgr: PermissionManager | None = None,
    ) -> None:
        self.engine: KnowledgeSearchEngine = (
            search_engine or KnowledgeSearchEngine()
        )
        self.sub_mgr: SubscriptionManager = (
            subscription_mgr or SubscriptionManager()
        )
        self.perm_mgr: PermissionManager = (
            permission_mgr or PermissionManager()
        )

    def handle_message(self, user_id: str, text: str) -> BotResponse:
        """统一消息入口：识别意图 → 权限检查 → 分发到对应处理器。

        Args:
            user_id: 用户标识。
            text: 用户输入文本。

        Returns:
            Bot 响应。
        """
        intent, params = recognize_intent(text)
        required = _INTENT_PERMISSIONS.get(intent, Permission.READ)

        if not self.perm_mgr.check(user_id, required):
            return BotResponse(text="❌ 权限不足")

        handlers: dict[Intent, Any] = {
            Intent.SEARCH: self._handle_search,
            Intent.TODAY: self._handle_today,
            Intent.TOP: self._handle_top,
            Intent.RECOMMEND: self._handle_recommend,
            Intent.SUBSCRIBE: self._handle_subscribe,
            Intent.HELP: self._handle_help,
            Intent.UNKNOWN: self._handle_unknown,
        }

        handler = handlers[intent]
        return handler(user_id, params)

    def _handle_search(self, user_id: str, query: str) -> BotResponse:
        if not query:
            return BotResponse(
                text="请输入搜索关键词，例如：\n`/search RAG`\n`/search Agent`",
            )

        articles = self.engine.search(keyword=query, top_n=5)

        if not articles:
            return BotResponse(
                text=f"未找到与 「{query}」 匹配的结果",
            )

        from distribution.formatter import json_to_feishu, json_to_markdown

        md_parts: list[str] = [f"### 🔍 搜索结果：{query}", ""]
        cards: list[dict[str, Any]] = []

        for art in articles:
            md_parts.append(json_to_markdown(art))
            cards.append(json_to_feishu(art))

        return BotResponse(
            text="\n".join(md_parts),
            feishu_cards=cards,
        )

    def _handle_today(self, user_id: str, _: str) -> BotResponse:
        from distribution.formatter import generate_daily_digest

        digest = generate_daily_digest(
            knowledge_dir=self.engine.articles_dir,
            top_n=5,
        )
        return BotResponse(
            text=digest["markdown"],
            feishu_cards=digest["feishu"],
        )

    def _handle_top(self, user_id: str, n_str: str) -> BotResponse:
        try:
            n = max(1, min(20, int(n_str)))
        except (ValueError, TypeError):
            n = 5

        articles = self.engine.get_top(top_n=n)

        if not articles:
            return BotResponse(text="📭 今日暂无热门文章")

        from distribution.formatter import json_to_feishu, json_to_markdown

        md_parts: list[str] = [f"### 🏆 今日热门 Top {n}", ""]
        cards: list[dict[str, Any]] = []

        for i, art in enumerate(articles, 1):
            md_parts.append(f"**{i}. {art.get('title', '无标题')}**")
            md_parts.append(json_to_markdown(art))
            cards.append(json_to_feishu(art))

        return BotResponse(
            text="\n".join(md_parts),
            feishu_cards=cards,
        )

    def _handle_recommend(self, user_id: str, n_str: str) -> BotResponse:
        try:
            n = max(1, min(20, int(n_str)))
        except (ValueError, TypeError):
            n = 5

        articles_dir = self.engine.articles_dir
        articles: list[dict[str, Any]] = []

        for fname in os.listdir(articles_dir):
            if not fname.endswith(".json") or fname == "index.json":
                continue
            try:
                with open(os.path.join(articles_dir, fname), encoding="utf-8") as f:
                    article = json.load(f)
            except (OSError, ValueError):
                continue

            score = article.get("score")
            if score is not None:
                articles.append(article)

        seen: dict[str, dict[str, Any]] = {}
        for art in articles:
            title = art.get("title", "")
            score = art.get("score", 0) or 0
            prev = seen.get(title, {}).get("score", 0) or 0
            if title not in seen or score > prev:
                seen[title] = art

        scored = sorted(
            seen.values(),
            key=lambda a: a.get("score", 0) or 0,
            reverse=True,
        )
        top = scored[:n]

        if not top:
            return BotResponse(text="📭 暂无高分文章")

        from distribution.formatter import json_to_feishu, json_to_markdown

        md_parts: list[str] = [f"### ⭐ 高分推荐 Top {n}", ""]
        cards: list[dict[str, Any]] = []

        for i, art in enumerate(top, 1):
            md_parts.append(f"**{i}. {art.get('title', '无标题')}**")
            md_parts.append(json_to_markdown(art))
            cards.append(json_to_feishu(art))

        return BotResponse(
            text="\n".join(md_parts),
            feishu_cards=cards,
        )

    def _handle_subscribe(self, user_id: str, _: str) -> BotResponse:
        subscribed = self.sub_mgr.subscribe(user_id)
        if subscribed:
            return BotResponse(
                text="✅ 订阅成功！每日简报将定时推送给你。",
            )
        return BotResponse(text="已取消订阅，不再推送每日简报。")

    def _handle_help(self, user_id: str, _: str) -> BotResponse:
        help_text = (
            "**🤖 知识库助手使用指南**\n\n"
            "**命令列表**\n"
            "`/search <关键词>` — 搜索知识库\n"
            "`/today` — 查看今日简报\n"
            "`/top [N]` — 今日热门 Top N（默认 5）\n"
            "`/recommend [N]` — 高分推荐 Top N（默认 5）\n"
            "`/subscribe` — 订阅/取消每日推送\n"
            "`/help` — 显示帮助\n\n"
            "**使用示例**\n"
            "搜索：`/search RAG`、`/search Agent`\n"
            "高分推荐：`/recommend`、`/recommend 10`、`推荐几篇文章`"
        )
        return BotResponse(text=help_text)

    def _handle_unknown(self, user_id: str, text: str) -> BotResponse:
        return BotResponse(
            text="未识别的指令，请发送 `/help` 查看可用命令。",
        )
