"""V3 多 Agent 工作流图定义。

                ┌──────────┐
                │   plan   │
                └────┬─────┘
                     │
                ┌────▼──────┐
                │  collect  │
                └────┬──────┘
                     │
                ┌────▼──────┐
                │  analyze  │
                └────┬──────┘
                     │
                ┌────▼───────┐
                │  organize  │
                └────┬───────┘
                     │
                ┌────▼───────┐
                │   review   │
                └────┬───────┘
                     │
           ┌─────────┴──────────┐
           │  review_passed?    │
           ├─ True               ├─ False (iteration<2)
           │                     │    → revise → organize → review
           │                     │
           │              ┌──────▼──────┐
           │              │   revise    │
           │              └──────┬──────┘
           │                     │
           │              ┌──────▼──────┐
           │              │  organize   │
           │              └──────┬──────┘
           │                     │
           │              ┌──────▼──────┐
           │              │   review    │
           │              └──────┬──────┘
           │                     │ (forced pass if iteration>=2)
           │                     │
           │              ┌──────▼──────────┐
           │              │  human_flag     │
           │              └──────┬──────────┘
           │                     │
           │              ┌──────▼──────┐
           │              │    save     │
           │              └──────┬──────┘
           │                     │
           │                ┌────▼────┐
           └────────────────►  END   │
                            └─────────┘

Usage::

    from v3_multi_agent.workflows.graph import build_graph

    app = build_graph()
    result = app.invoke(initial_state)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from langgraph.graph import END, StateGraph

_workflows_dir = str(Path(__file__).resolve().parent)
if _workflows_dir not in sys.path:
    sys.path.insert(0, _workflows_dir)

from collector_agent import collector_agent  # type: ignore[import-untyped]
from analyzer_agent import analyzer_agent  # type: ignore[import-untyped]
from organizer_agent import organizer_agent  # type: ignore[import-untyped]
from reviewer_agent import reviewer_agent  # type: ignore[import-untyped]
from reviser_agent import reviser_agent  # type: ignore[import-untyped]
from planner_agent import planner_agent  # type: ignore[import-untyped]
from human_flag_agent import human_flag_agent  # type: ignore[import-untyped]
from nodes import save_node  # type: ignore[import-untyped]
from state import KBState  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ====================================================================
#  路由函数
# ====================================================================


def review_router(state: dict) -> str:
    if state.get("review_passed", False):
        return "human_flag"
    return "revise"


# ====================================================================
#  构建函数
# ====================================================================


def build_graph() -> StateGraph:
    graph = StateGraph(KBState)

    graph.add_node("planner", planner_agent)
    graph.add_node("collect", collector_agent)
    graph.add_node("analyze", analyzer_agent)
    graph.add_node("organize", organizer_agent)
    graph.add_node("review", reviewer_agent)
    graph.add_node("revise", reviser_agent)
    graph.add_node("human_flag", human_flag_agent)
    graph.add_node("save", save_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    graph.add_conditional_edges(
        "review",
        review_router,
        {"human_flag": "human_flag", "revise": "revise"},
    )

    graph.add_edge("revise", "organize")
    graph.add_edge("human_flag", "save")
    graph.add_edge("save", END)

    return graph.compile()


# ====================================================================
#  自测入口 — 流式执行并打印每节点关键信息
# ====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    app = build_graph()

    initial: KBState = {
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

    print("V3 工作流开始执行")
    print("=" * 50)

    for event in app.stream(initial):
        for node_name, updates in event.items():
            print(f"\n=== {node_name} ===")
            if isinstance(updates, dict):
                for key, value in updates.items():
                    if isinstance(value, list):
                        print(f"  {key}: {len(value)} items")
                    elif isinstance(value, dict) and "calls" in value:
                        print(
                            f"  cumulative: calls={value['calls']}, "
                            f"prompt_tokens={value.get('total_prompt_tokens', 0)}, "
                            f"completion_tokens={value.get('total_completion_tokens', 0)}"
                        )
                    elif isinstance(value, bool):
                        print(f"  {key}: {value}")
                    else:
                        display = str(value)[:60]
                        print(f"  {key}: {display}")

    print()
    print("=" * 50)
    print("V3 工作流执行完成")

    from workflows.model_client import get_cost_guard

    guard = get_cost_guard()
    report = guard.get_report()
    s = report["summary"]
    print(f"[CostGuard] 总调用 {s['total_calls']} 次 · "
          f"总成本 ¥{s['total_cost_yuan']} · "
          f"预算 ¥{s['budget_yuan']}")
    if report["by_node"]:
        print("[CostGuard] 按节点:")
        for node, stats in report["by_node"].items():
            print(f"    {node}: {stats['calls']} 次, ¥{stats['cost_yuan']}")
