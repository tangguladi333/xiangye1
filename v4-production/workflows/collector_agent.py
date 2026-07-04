from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from _shared import (
    GITHUB_API_URL,
    _GITHUB_PER_PAGE,
    _GITHUB_TRENDING_URL,
    _GITHUB_TRENDING_MAX,
    build_github_queries,
    load_recent_article_urls,
    make_article_id,
    now_iso,
    sanitize_input,
)

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _collect_trending(seen_urls: set[str]) -> list[dict]:
    logger.info("[CollectorAgent] 开始爬取 GitHub Trending...")
    sources: list[dict] = []

    try:
        req = urllib.request.Request(
            _GITHUB_TRENDING_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        logger.warning("[CollectorAgent] GitHub Trending 请求失败: %s", e)
        return sources

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("article.Box-row")

    for row in rows:
        if len(sources) >= _GITHUB_TRENDING_MAX:
            break

        h2 = row.select_one("h2")
        if not h2:
            continue
        link = h2.select_one("a")
        if not link:
            continue
        href = link.get("href", "")
        full_name = href.strip("/")
        url_repo = f"https://github.com/{full_name}"

        if url_repo in seen_urls:
            continue
        seen_urls.add(url_repo)

        p_desc = row.select_one("p")
        description = p_desc.get_text(strip=True) if p_desc else ""

        lang_el = row.select_one("[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else ""

        stars_el = row.select_one(f"a[href='/{full_name}/stargazers']")
        stars = 0
        if stars_el:
            stars_text = stars_el.get_text(strip=True).replace(",", "")
            m = re.search(r"(\d+(?:\.\d+)?)([kK])?", stars_text)
            if m:
                val = float(m.group(1))
                if m.group(2) and m.group(2).lower() == "k":
                    val *= 1000
                stars = int(val)

        source: dict = {
            "id": make_article_id("github", full_name),
            "title": full_name,
            "url": url_repo,
            "source_type": "github_trending",
            "collected_at": now_iso(),
            "description": description,
            "language": language,
            "stars": stars,
        }
        sources.append(source)

    logger.info(
        "[CollectorAgent] Trending 爬取完成，新增 %d 个", len(sources)
    )
    return sources


def collector_agent(state: dict) -> dict:
    logger.info("[CollectorAgent] 开始采集 GitHub AI 仓库...")

    seen_urls: set[str] = load_recent_article_urls()
    sources: list[dict] = []

    # ── 分支 A：GitHub Search ──────────────────────────────────────
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

    # ── 分支 B：GitHub Trending 页面 ──────────────────────────────
    trending = _collect_trending(seen_urls)
    sources.extend(trending)

    # ── 安全过滤 ──────────────────────────────────────────────────
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
