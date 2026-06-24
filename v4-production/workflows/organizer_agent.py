from __future__ import annotations

import logging

from _shared import _QUALITY_THRESHOLD, make_article_id, now_iso, filter_output

logger = logging.getLogger(__name__)


def organizer_agent(state: dict) -> dict:
    logger.info("[OrganizerAgent] 开始整理分析结果...")

    analyses: list[dict] = state.get("analyses", [])
    cost_tracker = dict(state.get("cost_tracker", {}))

    if not analyses:
        logger.info("[OrganizerAgent] 无待整理数据")
        return {"articles": [], "cost_tracker": cost_tracker}

    filtered = [a for a in analyses if a.get("quality_score", 0) >= _QUALITY_THRESHOLD]
    dropped = len(analyses) - len(filtered)
    if dropped:
        logger.info(f"[OrganizerAgent] 过滤低分: {dropped} 条")

    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for a in filtered:
        matched_source = next(
            (s for s in state.get("sources", []) if s.get("id") == a.get("source_id")),
            None,
        )
        url = matched_source.get("url", "") if matched_source else ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(a)

    dup_count = len(filtered) - len(deduped)
    if dup_count:
        logger.info(f"[OrganizerAgent] 去重: {dup_count} 条")

    articles: list[dict] = []
    for a in deduped:
        matched_source = next(
            (s for s in state.get("sources", []) if s.get("id") == a.get("source_id")),
            None,
        )
        article: dict = {
            "id": a.get("source_id", make_article_id("github", "unknown")),
            "title": matched_source.get("title", "") if matched_source else "",
            "source_url": matched_source.get("url", "") if matched_source else "",
            "source_type": (
                matched_source.get("source_type", "github_trending")
                if matched_source
                else "github_trending"
            ),
            "summary": a.get("summary", ""),
            "highlights": a.get("highlights", []),
            "use_cases": a.get("use_cases", []),
            "maturity": a.get("maturity", {}),
            "tags": a.get("tags", []),
            "status": "curated",
            "collected_at": (
                matched_source.get("collected_at", "") if matched_source else ""
            ),
            "analyzed_at": a.get("analyzed_at", ""),
            "curated_at": now_iso(),
        }
        articles.append(article)

    total_pii = 0
    for art in articles:
        for field in ("summary", "title"):
            val = art.get(field, "")
            if val:
                filtered_text, detections = filter_output(val, mask=True)
                if detections:
                    logger.warning(
                        "[Security] %s %s 掩码 PII: %s",
                        art.get("id", "?"),
                        field,
                        detections,
                    )
                    total_pii += len(detections)
                art[field] = filtered_text

    if total_pii:
        logger.info("[Security] organize 阶段共掩码 %d 处 PII", total_pii)

    logger.info(f"[OrganizerAgent] 整理完成，共 {len(articles)} 条")
    return {"articles": articles, "cost_tracker": cost_tracker}
