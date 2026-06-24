from __future__ import annotations

import logging

from _shared import chat_json, accumulate_usage, now_iso

logger = logging.getLogger(__name__)

_ANALYZE_SYSTEM: str = """你是一个 AI 技术分析专家。请分析以下 GitHub 仓库信息，
输出 JSON 格式的分析报告（只输出 JSON，不要额外文字）：

{
  "summary": "中文摘要（100 字以内）",
  "highlights": ["亮点1", "亮点2", "亮点3"],
  "use_cases": ["适用场景1", "适用场景2"],
  "quality_score": 0.85,
  "tags": ["llm", "agent"],
  "maturity": {
    "stars": 1200,
    "last_updated": "2026-06-01",
    "production_ready": false
  }
}

quality_score 为 0-1 之间的浮点数，综合评估项目的完整性、活跃度和实用性。"""


def analyzer_agent(state: dict) -> dict:
    logger.info("[AnalyzerAgent] 开始分析来源数据...")

    sources: list[dict] = state.get("sources", [])
    if not sources:
        logger.info("[AnalyzerAgent] 无待分析来源")
        return {"analyses": [], "cost_tracker": state.get("cost_tracker", {})}

    analyses: list[dict] = []
    cost_tracker = dict(state.get("cost_tracker", {}))

    for source in sources:
        repo_info = f"仓库: {source['title']}\n链接: {source['url']}"
        result = chat_json(
            prompt=repo_info,
            system=_ANALYZE_SYSTEM,
            temperature=0.3,
            node_name="analyzer_agent",
        )
        cost_tracker = accumulate_usage(cost_tracker, result["usage"])

        parsed = result["parsed"]
        if parsed is None:
            logger.warning("[AnalyzerAgent] JSON 解析失败，跳过: %s", source["title"])
            continue

        analysis: dict = {
            "source_id": source["id"],
            "summary": parsed.get("summary", ""),
            "highlights": parsed.get("highlights", []),
            "use_cases": parsed.get("use_cases", []),
            "quality_score": parsed.get("quality_score", 0.5),
            "maturity": parsed.get("maturity", {}),
            "tags": parsed.get("tags", []),
            "analyzed_at": now_iso(),
        }
        analyses.append(analysis)

    logger.info(f"[AnalyzerAgent] 分析完成，成功 {len(analyses)}/{len(sources)} 条")
    return {"analyses": analyses, "cost_tracker": cost_tracker}
