"""V3 多 Agent 工作流共享状态定义。

TypedDict 与根目录 workflows/state.py 保持一致，内联在此以避免循环 import。

Usage::

    from workflows.state import KBState

    def my_node(state: KBState) -> dict:
        return {"articles": state["articles"]}
"""

from __future__ import annotations

from typing import TypedDict


class SourceItem(TypedDict):
    id: str
    title: str
    url: str
    source_type: str
    collected_at: str


class AnalysisItem(TypedDict):
    source_id: str
    summary: str
    highlights: list[str]
    use_cases: list[str]
    maturity: dict
    tags: list[str]
    analyzed_at: str


class ArticleItem(TypedDict):
    id: str
    title: str
    source_url: str
    source_type: str
    summary: str
    highlights: list[str]
    use_cases: list[str]
    maturity: dict
    tags: list[str]
    status: str
    collected_at: str
    analyzed_at: str
    curated_at: str


class CostTracker(TypedDict):
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_cny: float
    calls: int


class KBState(TypedDict):
    plan: str
    plan_created_at: str
    sources: list[SourceItem]
    analyses: list[AnalysisItem]
    articles: list[ArticleItem]
    review_feedback: str
    review_passed: bool
    iteration: int
    cost_tracker: CostTracker
    needs_human_review: bool
    flagged_ids: list[str]


if __name__ == "__main__":
    import typing

    print("KBState 字段：")
    for field, annotation in typing.get_type_hints(KBState).items():
        print(f"  {field}: {annotation}")

    state: KBState = {
        "plan": "",
        "plan_created_at": "",
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "needs_human_review": False,
        "flagged_ids": [],
        "cost_tracker": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost_cny": 0.0,
            "calls": 0,
        },
    }

    print(f"\n共 {len(KBState.__annotations__)} 个字段")
    print(f"实例创建成功，iteration = {state['iteration']}")
