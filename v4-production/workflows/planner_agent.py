from __future__ import annotations

import json
import logging

from _shared import chat_json, now_iso

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM: str = """你是一个 AI 技术动态采集规划专家。请分析当前 AI 领域的技术趋势，
制定本次采集计划，输出 JSON 格式（只输出 JSON，不要额外文字）：

{
  "focus_topics": ["topic1", "topic2"],
  "search_queries": ["query1", "query2"],
  "reasoning": "选择这些主题的原因"
}

请确保搜索关键词是英文。"""


def planner_agent(state: dict) -> dict:
    logger.info("[PlannerAgent] 开始规划采集...")

    result = chat_json(
        prompt="请根据当前 AI 技术发展态势，制定本次采集计划。",
        system=_PLANNER_SYSTEM,
        node_name="planner_agent",
    )

    plan = result.get("parsed", {})
    logger.info(f"[PlannerAgent] 规划完成：{plan.get('focus_topics', [])}")

    return {
        "plan": json.dumps(plan, ensure_ascii=False) if plan else "{}",
        "plan_created_at": now_iso(),
    }
