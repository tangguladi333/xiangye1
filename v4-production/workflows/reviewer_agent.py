from __future__ import annotations

import json
import logging

from _shared import chat_json, accumulate_usage, _REVIEW_FORCE_PASS_ITERATION

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM: str = """你是一个质量审核专家。请审核以下知识条目列表，
从四个维度评分（每项 1-5 分）：

1. summary_quality（摘要质量）：摘要是否准确、简洁、有洞察深度
2. tag_accuracy（标签准确度）：标签是否准确反映内容
3. category_correctness（分类合理性）：条目分类是否合理
4. consistency（一致性）：各字段之间是否一致、无矛盾

综合四个维度给出 overall_score（1-5 分），并判断是否通过。

输出 JSON 格式（只输出 JSON，不要额外文字）：
{
  "passed": true,
  "overall_score": 3.5,
  "feedback": "具体的改进建议",
  "scores": {
    "summary_quality": 4,
    "tag_accuracy": 3,
    "category_correctness": 4,
    "consistency": 4
  }
}

passed = true 当 overall_score >= 3.5。"""


def reviewer_agent(state: dict) -> dict:
    logger.info("[ReviewerAgent] 开始审核...")

    articles: list[dict] = state.get("articles", [])
    iteration: int = state.get("iteration", 0) + 1
    cost_tracker = dict(state.get("cost_tracker", {}))

    if iteration >= _REVIEW_FORCE_PASS_ITERATION:
        logger.info(f"[ReviewerAgent] iteration={iteration} >= {_REVIEW_FORCE_PASS_ITERATION}，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "强制通过（超过审核轮次上限）",
            "iteration": iteration,
            "cost_tracker": cost_tracker,
        }

    if not articles:
        logger.info("[ReviewerAgent] 无条目可审核")
        return {
            "review_passed": True,
            "review_feedback": "无条目，自动通过",
            "iteration": iteration,
            "cost_tracker": cost_tracker,
        }

    articles_summary = [
        {"title": a.get("title", ""), "summary": a.get("summary", ""), "tags": a.get("tags", [])}
        for a in articles
    ]

    prompt = (
        f"请审核以下 {len(articles)} 条知识条目：\n"
        f"{json.dumps(articles_summary, ensure_ascii=False, indent=2)}"
    )
    result = chat_json(prompt=prompt, system=_REVIEW_SYSTEM, temperature=0.2, node_name="reviewer_agent")
    cost_tracker = accumulate_usage(cost_tracker, result["usage"])

    parsed = result["parsed"]
    if parsed is None:
        logger.warning("[ReviewerAgent] JSON 解析失败，默认通过")
        return {
            "review_passed": True,
            "review_feedback": "审核解析失败，自动通过",
            "iteration": iteration,
            "cost_tracker": cost_tracker,
        }

    passed: bool = parsed.get("passed", False)
    feedback: str = parsed.get("feedback", "")
    overall_score: float = parsed.get("overall_score", 3.0)

    logger.info(f"[ReviewerAgent] 评分 {overall_score:.1f}/5，通过={passed}，反馈={feedback[:40]}...")
    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration,
        "cost_tracker": cost_tracker,
    }
