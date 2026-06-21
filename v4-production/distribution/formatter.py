from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SOURCE_TYPE_LABELS: dict[str, str] = {
    "github_trending": "GitHub Trending",
    "hacker_news": "Hacker News",
}

_COMPLETED_NOTHING: str = "📭 {date} 暂无新增知识条目"


def _source_label(source_type: str) -> str:
    return _SOURCE_TYPE_LABELS.get(source_type, source_type)


def _star_score(stars: int) -> str:
    if stars >= 5000:
        return "🟢"
    if stars >= 1000:
        return "🟡"
    return "🔴"


def _star_template(stars: int) -> str:
    if stars >= 5000:
        return "green"
    if stars >= 1000:
        return "yellow"
    return "red"


def _escape_feishu_md(text: str) -> str:
    for ch in r"_*[]~`>#+-=|{}":
        text = text.replace(ch, f"\\{ch}")
    return text


def json_to_markdown(article: dict) -> str:
    """将单篇文章转换为可读的 Markdown 格式。

    Args:
        article: Organizer 节点产出的知识条目字典。

    Returns:
        格式化的 Markdown 字符串。
    """
    title = article.get("title", "无标题")
    source_type = article.get("source_type", "unknown")
    source_label = _source_label(source_type)
    date_str = (article.get("collected_at") or "")[:10]
    stars = (article.get("maturity") or {}).get("stars", 0)
    emoji = _star_score(stars)
    tags_str = " ".join(f"`{tag}`" for tag in article.get("tags", []))
    summary = article.get("summary", "暂无摘要")
    highlights: list[str] = article.get("highlights", [])
    source_url = article.get("source_url", "")

    parts: list[str] = [f"## {title}", ""]
    parts.append(f"- **来源**：{source_label}")
    if date_str:
        parts.append(f"- **日期**：{date_str}")
    parts.append(f"- **热度**：{emoji} ⭐{stars}")
    if tags_str:
        parts.append(f"- **标签**：{tags_str}")
    parts.append("")
    parts.append(summary)
    parts.append("")

    if highlights:
        parts.append("**亮点**：")
        for h in highlights[:3]:
            parts.append(f"- {h}")
        parts.append("")

    if source_url:
        parts.append(f"🔗 [原文链接]({source_url})")
    parts.append("")
    parts.append("---")

    return "\n".join(parts)


def json_to_feishu(article: dict) -> dict:
    """将单篇文章转换为飞书 interactive 卡片消息。

    Args:
        article: Organizer 节点产出的知识条目字典。

    Returns:
        飞书消息 API 请求体（msg_type: interactive）。
    """
    title = article.get("title", "无标题")
    summary = article.get("summary", "暂无摘要")
    highlights: list[str] = article.get("highlights", [])[:3]
    tags: list[str] = article.get("tags", [])
    source_url = article.get("source_url", "")
    source_type = article.get("source_type", "unknown")
    stars = (article.get("maturity") or {}).get("stars", 0)
    template = _star_template(stars)
    date_str = (article.get("collected_at") or "")[:10]

    elements: list[dict[str, Any]] = []

    elements.append({
        "tag": "markdown",
        "content": f"**摘要**\n{_escape_feishu_md(summary)}",
    })

    if highlights:
        hl_text = "**亮点**\n" + "\n".join(
            f"- {_escape_feishu_md(h)}" for h in highlights
        )
        elements.append({"tag": "markdown", "content": hl_text})

    meta_parts: list[str] = [
        f"📊 热度：⭐{stars}",
        f"📅 来源：{_source_label(source_type)}",
    ]
    if date_str:
        meta_parts.append(f"📅 {date_str}")
    if tags:
        meta_parts.append("🏷 " + " ".join(f"#{t}" for t in tags))

    if meta_parts:
        elements.append({"tag": "markdown", "content": " | ".join(meta_parts)})

    if source_url:
        elements.append({
            "tag": "markdown",
            "content": f"🔗 [原文链接]({source_url})",
        })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        },
    }


def generate_daily_digest(
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
) -> dict:
    """生成每日知识简报。

    扫描 knowledge_dir 中指定日期的文章，按 star 数降序取前 top_n 条，
    同时输出 Markdown 和飞书卡片两种格式。

    Args:
        knowledge_dir: 文章目录路径，默认 "knowledge/articles"。
        date: 日期 "YYYY-MM-DD"，默认今天。
        top_n: 返回条数上限，默认 5。

    Returns:
        当日有文章时返回 {"markdown": str, "feishu": list[dict]}，
        无文章时 markdown 为占位提示，feishu 为空列表。
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    date_fmt = date.replace("-", "")
    articles_dir = Path(knowledge_dir)
    articles: list[dict] = []

    for fp in sorted(articles_dir.glob(f"{date_fmt}-*.json")):
        try:
            with open(fp, encoding="utf-8") as f:
                articles.append(json.load(f))
        except (OSError, ValueError) as e:
            logger.warning("跳过文件 %s: %s", fp, e)

    if not articles:
        return {
            "markdown": _COMPLETED_NOTHING.format(date=date),
            "feishu": [],
        }

    articles.sort(
        key=lambda a: (a.get("maturity") or {}).get("stars", 0),
        reverse=True,
    )
    top_articles = articles[:top_n]

    md_parts: list[str] = [f"# 📋 知识简报 · {date}", ""]
    feishu_cards: list[dict] = []

    for i, art in enumerate(top_articles, 1):
        md_parts.append(f"### {i}. {art.get('title', '无标题')}")
        md_parts.append(json_to_markdown(art))
        feishu_cards.append(json_to_feishu(art))

    return {
        "markdown": "\n".join(md_parts),
        "feishu": feishu_cards,
    }
