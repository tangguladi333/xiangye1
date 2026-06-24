from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from _shared import (
    GITHUB_API_URL,
    build_github_queries,
    load_recent_article_urls,
    _GITHUB_PER_PAGE,
    make_article_id,
    now_iso,
    sanitize_input,
)

logger = logging.getLogger(__name__)


def collector_agent(state: dict) -> dict:
    logger.info("[CollectorAgent] 开始采集 GitHub AI 仓库...")

    seen_urls: set[str] = load_recent_article_urls()
    sources: list[dict] = []

    for query in build_github_queries():
        params = urllib.parse.urlencode(
            {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": _GITHUB_PER_PAGE,
            }
        )
        url = f"{GITHUB_API_URL}?{params}"

        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning(
                "[CollectorAgent] GitHub API HTTP error for %r: %s", query, e
            )
            continue
        except urllib.error.URLError as e:
            logger.warning(
                "[CollectorAgent] GitHub API connection error for %r: %s", query, e
            )
            continue

        items = data.get("items", [])
        for item in items:
            url_repo = item.get("html_url", "")
            if url_repo in seen_urls:
                continue
            seen_urls.add(url_repo)

            source: dict = {
                "id": make_article_id("github", item.get("full_name", "")),
                "title": item.get("full_name", "unknown"),
                "url": url_repo,
                "source_type": "github_trending",
                "collected_at": now_iso(),
            }
            sources.append(source)

    total_warnings = 0
    for s in sources:
        cleaned, warnings = sanitize_input(s.get("title", ""))
        if warnings:
            logger.warning(
                "[Security] %s title 检出注入模式: %s", s.get("url", "?"), warnings
            )
            total_warnings += len(warnings)
        s["title"] = cleaned

    if total_warnings:
        logger.info("[Security] collect 阶段共拦截 %d 处可疑输入", total_warnings)

    logger.info(f"[CollectorAgent] 采集完成，共 {len(sources)} 个来源")
    return {"sources": sources}
