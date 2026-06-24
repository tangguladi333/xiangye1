from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SENSITIVE_KEYWORDS: list[str] = [
    "security",
    "vulnerability",
    "exploit",
    "attack",
    "安全",
    "漏洞",
    "攻击",
    "利用",
]


def human_flag_agent(state: dict) -> dict:
    logger.info("[HumanFlagAgent] 检查是否需要人工审核...")

    articles: list[dict] = state.get("articles", [])
    flagged: list[str] = []

    for art in articles:
        title = art.get("title", "")
        summary = art.get("summary", "")
        combined = f"{title} {summary}".lower()

        if any(kw in combined for kw in _SENSITIVE_KEYWORDS):
            flagged.append(art.get("id", ""))
            logger.info("[HumanFlagAgent] 标记人工审核: %s", art.get("title", "?"))

    return {
        "needs_human_review": len(flagged) > 0,
        "flagged_ids": flagged,
    }
