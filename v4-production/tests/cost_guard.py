"""多 Agent 预算守卫。

三重保护机制：
  1. 记录 — 追踪每次 LLM 调用的 token 用量与成本
  2. 预警 — 接近预算时返回 warning 状态
  3. 拦截 — 超出预算时抛出 BudgetExceededError

Usage::
    guard = CostGuard(budget_yuan=1.0)
    guard.record("analyze_node", {"prompt_tokens": 500, "completion_tokens": 200})
    status = guard.check()
    report = guard.get_report()
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class BudgetExceededError(Exception):
    """预算超限异常，当累计成本超过 budget_yuan 时抛出。"""

    def __init__(self, total_cost: float, budget: float) -> None:
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(f"预算超限: ¥{total_cost:.4f} > ¥{budget:.4f}")


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。"""

    timestamp: str
    """ISO 8601 时间戳。"""
    node_name: str
    """调用节点名称。"""
    prompt_tokens: int
    """输入 token 数。"""
    completion_tokens: int
    """输出 token 数。"""
    cost_yuan: float
    """本次调用费用（人民币元）。"""
    model: str = ""
    """模型名称，可选。"""


@dataclass
class CostGuard:
    """多 Agent 预算守卫。

    Args:
        budget_yuan: 总预算上限（人民币元），默认 1.0。
        alert_threshold: 预警阈值（占 budget 的比例），默认 0.8。
        input_price_per_million: 输入价格（元/百万 token），默认 1.0。
        output_price_per_million: 输出价格（元/百万 token），默认 2.0。
    """

    budget_yuan: float = 1.0
    alert_threshold: float = 0.8
    input_price_per_million: float = 1.0
    output_price_per_million: float = 2.0
    records: list[CostRecord] = field(default_factory=list)

    def record(
        self,
        node_name: str,
        usage: dict,
        model: str = "",
    ) -> CostRecord:
        """记录一次 LLM 调用的 token 用量。

        Args:
            node_name: 调用节点名称。
            usage: 用量字典，格式 {"prompt_tokens": int, "completion_tokens": int}。
            model: 模型名称，可选。

        Returns:
            创建的 CostRecord。
        """
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)

        cost = (
            prompt / 1_000_000 * self.input_price_per_million
            + completion / 1_000_000 * self.output_price_per_million
        )

        record = CostRecord(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            node_name=node_name,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_yuan=round(cost, 8),
            model=model,
        )
        self.records.append(record)
        return record

    def check(self) -> dict:
        """检查预算状态。

        Returns:
            {
                "status": "ok" | "warning" | "exceeded",
                "total_cost": float,
                "budget": float,
                "usage_ratio": float,
                "message": str,
            }

        Raises:
            BudgetExceededError: 当总成本超过 budget_yuan 时抛出。
        """
        total_cost = sum(r.cost_yuan for r in self.records)
        usage_ratio = total_cost / self.budget_yuan if self.budget_yuan > 0 else 0.0

        if total_cost >= self.budget_yuan:
            raise BudgetExceededError(total_cost=total_cost, budget=self.budget_yuan)

        if usage_ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": round(total_cost, 6),
                "budget": self.budget_yuan,
                "usage_ratio": round(usage_ratio, 4),
                "message": (
                    f"预算接近上限: ¥{total_cost:.4f} / ¥{self.budget_yuan:.4f} "
                    f"({usage_ratio:.1%})"
                ),
            }

        return {
            "status": "ok",
            "total_cost": round(total_cost, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(usage_ratio, 4),
            "message": f"预算正常: ¥{total_cost:.4f} / ¥{self.budget_yuan:.4f}",
        }

    def get_report(self) -> dict:
        """生成成本报告（按节点分组统计）。

        Returns:
            {
                "summary": {"total_calls", "total_cost", "budget", ...},
                "by_node": {node_name: {"calls", "prompt_tokens", "completion_tokens", "cost_yuan"}, ...},
                "records": [CostRecord, ...],
            }
        """
        total_prompt = sum(r.prompt_tokens for r in self.records)
        total_completion = sum(r.completion_tokens for r in self.records)
        total_cost = sum(r.cost_yuan for r in self.records)

        by_node: dict[str, dict] = {}
        for r in self.records:
            node = r.node_name
            if node not in by_node:
                by_node[node] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                }
            by_node[node]["calls"] += 1
            by_node[node]["prompt_tokens"] += r.prompt_tokens
            by_node[node]["completion_tokens"] += r.completion_tokens
            by_node[node]["cost_yuan"] = round(
                by_node[node]["cost_yuan"] + r.cost_yuan, 8
            )

        return {
            "summary": {
                "total_calls": len(self.records),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_cost_yuan": round(total_cost, 6),
                "budget_yuan": self.budget_yuan,
                "usage_ratio": (
                    round(total_cost / self.budget_yuan, 4)
                    if self.budget_yuan > 0
                    else 0.0
                ),
            },
            "by_node": by_node,
            "records": [r.__dict__ for r in self.records],
        }

    def save_report(self, path: Optional[str] = None) -> str:
        """保存成本报告到 JSON 文件。

        Args:
            path: 保存路径，默认 "cost_report_{timestamp}.json"。

        Returns:
            实际保存的文件路径。
        """
        if path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"cost_report_{ts}.json"

        report = self.get_report()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return os.path.abspath(path)


# ====================================================================
#  测试
# ====================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("CostGuard 测试")
    print("=" * 50)

    # ------------------------------------------------------------------
    #  测试 1：成本追踪正确性
    # ------------------------------------------------------------------
    print("\n>>> 测试 1: 成本追踪正确性")
    guard = CostGuard(
        budget_yuan=1.0,
        alert_threshold=0.8,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    guard.record("collect_node", {"prompt_tokens": 100, "completion_tokens": 50})
    guard.record("analyze_node", {"prompt_tokens": 500, "completion_tokens": 200})
    guard.record("review_node", {"prompt_tokens": 200, "completion_tokens": 100})

    report = guard.get_report()
    s = report["summary"]
    total_prompt = s["total_prompt_tokens"]
    total_completion = s["total_completion_tokens"]
    total_cost = s["total_cost_yuan"]

    assert total_prompt == 800, f"预期 800, 实际 {total_prompt}"
    assert total_completion == 350, f"预期 350, 实际 {total_completion}"

    expected_cost = (
        100 / 1_000_000 * 1.0
        + 50 / 1_000_000 * 2.0
        + 500 / 1_000_000 * 1.0
        + 200 / 1_000_000 * 2.0
        + 200 / 1_000_000 * 1.0
        + 100 / 1_000_000 * 2.0
    )
    assert (
        abs(total_cost - expected_cost) < 1e-6
    ), f"预期 {expected_cost}, 实际 {total_cost}"

    print(f"  prompt_tokens: {total_prompt}  ✅")
    print(f"  completion_tokens: {total_completion}  ✅")
    print(f"  total_cost: ¥{total_cost:.6f}  ✅")
    print("  → 测试 1 通过")

    # ------------------------------------------------------------------
    #  测试 2：预算超限检测
    # ------------------------------------------------------------------
    print("\n>>> 测试 2: 预算超限检测")
    guard2 = CostGuard(
        budget_yuan=0.005,
        alert_threshold=0.8,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    guard2.record("big_call", {"prompt_tokens": 3000, "completion_tokens": 1500})
    # 3K prompt: 3000/1e6*1.0 = 0.003
    # 1.5K completion: 1500/1e6*2.0 = 0.003
    # total = 0.006 > 0.005 budget

    try:
        guard2.check()
        assert False, "应该抛出 BudgetExceededError"
    except BudgetExceededError as e:
        print(f"  异常信息: {e}")
        print(f"  total_cost=¥{e.total_cost:.4f}, budget=¥{e.budget:.4f}  ✅")
        print("  → 测试 2 通过")

    # ------------------------------------------------------------------
    #  测试 3：预警阈值触发
    # ------------------------------------------------------------------
    print("\n>>> 测试 3: 预警阈值触发")
    guard3 = CostGuard(
        budget_yuan=0.01,
        alert_threshold=0.5,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    guard3.record("medium_call", {"prompt_tokens": 3000, "completion_tokens": 1000})
    # 3K prompt: 0.003, 1K completion: 0.002, total = 0.005
    # ratio = 0.005/0.01 = 0.5 >= 0.5 → warning

    status = guard3.check()
    assert status["status"] == "warning", f"预期 warning, 实际 {status['status']}"
    print(f"  status: {status['status']}  ✅")
    print(f"  total_cost: ¥{status['total_cost']:.4f}")
    print(f"  usage_ratio: {status['usage_ratio']:.0%}")
    print(f"  message: {status['message']}")
    print("  → 测试 3 通过")

    # ------------------------------------------------------------------
    #  测试 4：正常状态
    # ------------------------------------------------------------------
    print("\n>>> 测试 4: 正常状态")
    guard4 = CostGuard(
        budget_yuan=1.0,
        alert_threshold=0.8,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    guard4.record("small_call", {"prompt_tokens": 100, "completion_tokens": 50})
    status4 = guard4.check()
    assert status4["status"] == "ok", f"预期 ok, 实际 {status4['status']}"
    print(f"  status: {status4['status']}  ✅")
    print(f"  total_cost: ¥{status4['total_cost']:.6f}")
    print(f"  usage_ratio: {status4['usage_ratio']:.2%}")
    print("  → 测试 4 通过")

    # ------------------------------------------------------------------
    #  测试 5：按节点分组报告
    # ------------------------------------------------------------------
    print("\n>>> 测试 5: 按节点分组报告")
    guard5 = CostGuard(budget_yuan=1.0)
    guard5.record("node_a", {"prompt_tokens": 100, "completion_tokens": 50})
    guard5.record("node_a", {"prompt_tokens": 200, "completion_tokens": 100})
    guard5.record("node_b", {"prompt_tokens": 50, "completion_tokens": 25})

    report5 = guard5.get_report()
    assert (
        report5["by_node"]["node_a"]["calls"] == 2
    ), f"预期 2 次, 实际 {report5['by_node']['node_a']['calls']}"
    assert (
        report5["by_node"]["node_b"]["calls"] == 1
    ), f"预期 1 次, 实际 {report5['by_node']['node_b']['calls']}"
    assert report5["summary"]["total_calls"] == 3
    print(f"  node_a: {report5['by_node']['node_a']['calls']} calls  ✅")
    print(f"  node_b: {report5['by_node']['node_b']['calls']} calls  ✅")
    print(f"  total_calls: {report5['summary']['total_calls']}  ✅")
    print("  → 测试 5 通过")

    # ------------------------------------------------------------------
    #  测试 6：svae_report 写入
    # ------------------------------------------------------------------
    print("\n>>> 测试 6: save_report 写入")
    guard6 = CostGuard(budget_yuan=1.0)
    guard6.record("test", {"prompt_tokens": 100, "completion_tokens": 50})
    path = guard6.save_report()
    assert os.path.exists(path), f"文件未创建: {path}"
    with open(path) as f:
        data = json.load(f)
    assert data["summary"]["total_calls"] == 1
    os.remove(path)
    print(f"  文件: {path}  ✅")
    print("  → 测试 6 通过")

    print("\n" + "=" * 50)
    print("全部测试通过 ✅")
    print("=" * 50)
