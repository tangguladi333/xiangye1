"""向后兼容模块 — 从 V3 agent 文件重新导出 5 个节点函数。

保持与 ``from workflows.nodes import collect_node, analyze_node, ...`` 相同的接口。
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_workflows_dir = str(Path(__file__).resolve().parent)
if _workflows_dir not in sys.path:
    sys.path.insert(0, _workflows_dir)

from _shared import update_index

logger = logging.getLogger(__name__)

BASE_DIR: str = _project_root
ARTICLES_DIR: str = os.path.join(BASE_DIR, "knowledge", "articles")

# ── 从 agent 文件导入（同目录，直接 import）────────────────────────
from collector_agent import collector_agent as collect_node  # type: ignore[import-untyped]
from analyzer_agent import analyzer_agent as analyze_node  # type: ignore[import-untyped]
from reviewer_agent import reviewer_agent as review_node  # type: ignore[import-untyped]
from organizer_agent import organizer_agent  # type: ignore[import-untyped]
from reviser_agent import reviser_agent  # type: ignore[import-untyped]


def organize_node(state: dict) -> dict:
    updates = organizer_agent(state)
    if state.get("iteration", 0) > 0 and state.get("review_feedback"):
        revise_updates = reviser_agent({**state, **updates})
        updates["articles"] = revise_updates.get("articles", updates.get("articles", []))
        updates["cost_tracker"] = revise_updates.get("cost_tracker", updates.get("cost_tracker", {}))
    return updates


# ── 保存节点（无对应 agent 文件，保留为内联实现）─────────────────


def save_node(state: dict) -> dict:
    """保存节点：将 articles 写入 knowledge/articles/ 并更新索引。"""
    logger.info("[SaveNode] 开始保存条目...")

    articles: list[dict] = state.get("articles", [])

    if not articles:
        logger.info("[SaveNode] 无条目可保存")
        return {"articles": articles}

    os.makedirs(ARTICLES_DIR, exist_ok=True)

    saved_count = 0
    for article in articles:
        article_id = article.get("id", "unknown")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", article_id)
        filepath = os.path.join(ARTICLES_DIR, f"{safe_name}.json")

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)
            saved_count += 1
        except OSError as e:
            logger.error("[SaveNode] 写入文件失败 %s: %s", filepath, e)

    update_index(ARTICLES_DIR)

    logger.info(f"[SaveNode] 保存完成，{saved_count}/{len(articles)} 条写入成功")
    return {"articles": articles}


__all__ = [
    "collect_node",
    "analyze_node",
    "organize_node",
    "review_node",
    "save_node",
]


# ── 集成测试 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    print("=" * 50)
    print("Workflow Nodes 集成测试 (V3 backward-compat)")
    print("=" * 50)

    state: dict = {
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

    print("\n>>> 步骤 1: 采集")
    updates = collect_node(state)
    state.update(updates)

    if not state["sources"]:
        print("采集结果为空（可能是 GitHub API 限流），跳过后续步骤。")
        sys.exit(1)
    print(f"   来源数: {len(state['sources'])}")

    print("\n>>> 步骤 2: 分析")
    updates = analyze_node(state)
    state.update(updates)
    print(f"   分析数: {len(state['analyses'])}")

    print("\n>>> 步骤 3: 整理")
    updates = organize_node(state)
    state.update(updates)
    print(f"   条目数: {len(state['articles'])}")

    print("\n>>> 步骤 4: 审核")
    updates = review_node(state)
    state.update(updates)
    print(f"   通过: {state['review_passed']}, 轮次: {state['iteration']}")

    if not state["review_passed"] and state["iteration"] < 4:
        print(f"\n>>> 第 {state['iteration']} 轮未通过，执行重试...")
        updates = organize_node(state)
        state.update(updates)
        updates = review_node(state)
        state.update(updates)
        print(f"   通过: {state['review_passed']}, 轮次: {state['iteration']}")

    print("\n>>> 步骤 5: 保存")
    updates = save_node(state)
    state.update(updates)

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)
    print(f"  来源: {len(state['sources'])}")
    print(f"  分析: {len(state['analyses'])}")
    print(f"  条目: {len(state['articles'])}")
    print(f"  审核: {'通过' if state['review_passed'] else '未通过'} (轮次 {state['iteration']})")
    print(f"  Token: {state['cost_tracker']['total_prompt_tokens']} prompt / {state['cost_tracker']['total_completion_tokens']} completion")
    print(f"  调用: {state['cost_tracker']['calls']} 次")
