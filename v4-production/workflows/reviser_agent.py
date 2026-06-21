from __future__ import annotations

import json
import logging

from _shared import chat_json, accumulate_usage

logger = logging.getLogger(__name__)

_REVISE_SYSTEM: str = """你是一个知识整理专家。用户会给你一篇已有的分析报告
和审核反馈意见，请根据反馈定向修改报告内容。

输出 JSON 格式（只输出 JSON，不要额外文字）：
{
  "summary": "修正后的摘要",
  "tags": ["修正后的标签列表"],
  "highlights": ["修正后的亮点列表"]
}

只修正 feedback 中指出的问题，其他内容保持不变。"""


def reviser_agent(state: dict) -> dict:
    logger.info("[ReviserAgent] 开始根据审核反馈修正...")

    articles: list[dict] = state.get("articles", [])
    review_feedback: str = state.get("review_feedback", "")
    cost_tracker = dict(state.get("cost_tracker", {}))

    if not articles or not review_feedback:
        logger.info("[ReviserAgent] 无条目或无反馈，跳过修正")
        return {"articles": articles, "cost_tracker": cost_tracker}

    for art in articles:
        current_report = json.dumps({
            "summary": art.get("summary", ""),
            "tags": art.get("tags", []),
            "highlights": art.get("highlights", []),
        }, ensure_ascii=False)

        fix_prompt = (
            f"原报告：\n{current_report}\n\n"
            f"审核反馈：\n{review_feedback}\n\n"
            f"请根据反馈修正报告。"
        )
        fix_result = chat_json(
            prompt=fix_prompt,
            system=_REVISE_SYSTEM,
            temperature=0.3,
            node_name="reviser_agent",
        )
        cost_tracker = accumulate_usage(cost_tracker, fix_result["usage"])

        fix_data = fix_result["parsed"]
        if fix_data:
            art["summary"] = fix_data.get("summary", art["summary"])
            art["tags"] = fix_data.get("tags", art["tags"])
            art["highlights"] = fix_data.get("highlights", art["highlights"])
            logger.info(f"[ReviserAgent] 已修正: {art.get('title', '?')}")

    logger.info("[ReviserAgent] 修正完成")
    return {"articles": articles, "cost_tracker": cost_tracker}
