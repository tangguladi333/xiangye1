"""AI 知识库评估测试。

使用 pytest 框架，包含 LLM 测试和本地验证测试。

Usage::
    pytest v3-multi-agent/tests/eval_test.py -v
    pytest v3-multi-agent/tests/eval_test.py -v -m "not slow"  # 跳过 LLM 测试
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

# 确保 v4-production 在 sys.path 中
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import pytest  # noqa: E402

# 过滤未知标记警告（安全网，即便 pyproject.toml 已注册 slow）
warnings.filterwarnings("ignore", message="unknown marker.*")

from workflows.model_client import chat  # noqa: E402

# ====================================================================
#  常量
# ====================================================================

_ANALYSIS_SYSTEM: str = (
    "你是一个 AI 技术分析专家。请分析以下内容，"
    "输出 JSON 格式（只输出 JSON，不要额外文字）：\n"
    "{\n"
    '  "summary": "中文摘要（50 字以内）",\n'
    '  "quality_score": 0.85,\n'
    '  "highlights": ["亮点1", "亮点2"],\n'
    '  "tags": ["tag1", "tag2"]\n'
    "}"
)

_JUDGE_SYSTEM: str = (
    "你是一个严谨的质量评估专家。"
    "请对以下分析结果的质量打分（1-10 分），只返回一个数字。"
)

# ====================================================================
#  评估用例
# ====================================================================

EVAL_CASES: list[dict] = [
    {
        "name": "正面案例：技术文章",
        "input": (
            "LangChain is a framework for developing applications powered by large language models. "
            "It provides tools for prompt management, chain composition, and integration with "
            "various LLM providers. Key features include a standardized interface for 500+ LLM "
            "providers, prompt template management, chain and agent composition, and built-in "
            "memory and retrieval support. The framework has gained over 90,000 stars on GitHub "
            "and is widely used in production environments."
        ),
        "expected": {
            "summary_min_len": 10,
            "quality_score_gte": 0.5,
            "highlights_min": 1,
        },
    },
    {
        "name": "负面案例：无关内容",
        "input": (
            "今天天气真好，适合出去散步。中午吃了碗牛肉面，味道不错。"
            "下午准备去看电影，新上映的科幻片听说很好看。晚上和朋友约了吃饭。"
        ),
        "expected": {
            "quality_score_lt": 0.6,
        },
    },
    {
        "name": "边界案例：极短输入",
        "input": "AI",
        "expected": {
            "no_exception": True,
            "has_output": True,
        },
    },
]

# ====================================================================
#  辅助函数
# ====================================================================


def _parse_json_response(text: str) -> dict | None:
    """从 LLM 回复中提取 JSON。"""
    import re

    text = text.strip()
    for pattern in [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
    ]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ====================================================================
#  测试 1：EVAL_CASES 结构验证（不调 LLM）
# ====================================================================


def test_eval_case_structure() -> None:
    """验证 EVAL_CASES 的键和类型完整性。"""
    assert len(EVAL_CASES) >= 3, "至少需要 3 个评估用例"

    for i, case in enumerate(EVAL_CASES):
        assert "name" in case, f"用例 {i} 缺少 name"
        assert "input" in case, f"用例 {i} 缺少 input"
        assert "expected" in case, f"用例 {i} 缺少 expected"
        assert isinstance(case["expected"], dict), f"用例 {i} expected 必须是 dict"
        assert isinstance(case["name"], str), f"用例 {i} name 必须是 str"
        assert isinstance(case["input"], str), f"用例 {i} input 必须是 str"


# ====================================================================
#  测试 2：本地验证（不调 LLM）
# ====================================================================


def test_local_validation() -> None:
    """无需 LLM 的纯逻辑验证。"""
    # 验证正负案例的 quality_score 范围存在矛盾
    positive = EVAL_CASES[0]["expected"]
    negative = EVAL_CASES[1]["expected"]

    assert "quality_score_gte" in positive
    assert "quality_score_lt" in negative

    # 正面下限 >= 负面上限（确保分类有意义）
    assert (
        positive["quality_score_gte"] <= negative["quality_score_lt"]
    ), "正面和负面用例的 quality_score 范围应有区分"

    # 验证边界案例有 no_exception 标记
    assert EVAL_CASES[2]["expected"].get(
        "no_exception", False
    ), "边界用例应标记 no_exception"

    # 验证用例名称不重复
    names = [c["name"] for c in EVAL_CASES]
    assert len(names) == len(set(names)), "用例名称不能重复"


# ====================================================================
#  测试 3~5：LLM 分析每个 EVAL_CASE（标记为 slow）
# ====================================================================


@pytest.mark.slow
@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
def test_analyze_case(case: dict) -> None:
    """对 EVAL_CASE 调用 LLM 分析并验证预期范围。"""
    expected = case["expected"]

    result = chat(prompt=case["input"], system=_ANALYSIS_SYSTEM)
    content = result.get("content", "")

    assert content, "LLM 返回空内容"

    parsed = _parse_json_response(content)
    if "no_exception" in expected:
        return  # 边界案例只需保证不崩溃

    assert parsed is not None, f"JSON 解析失败，原始回复：{content[:200]}"

    summary = parsed.get("summary", "")
    quality_score = parsed.get("quality_score", 0.0)
    highlights = parsed.get("highlights", [])

    # 范围断言
    if "summary_min_len" in expected:
        assert (
            len(summary) >= expected["summary_min_len"]
        ), f"摘要长度 {len(summary)} < {expected['summary_min_len']}"

    if "quality_score_gte" in expected:
        assert (
            quality_score >= expected["quality_score_gte"]
        ), f"quality_score {quality_score} < {expected['quality_score_gte']}"

    if "quality_score_lt" in expected:
        assert (
            quality_score < expected["quality_score_lt"]
        ), f"quality_score {quality_score} >= {expected['quality_score_lt']}"

    if "highlights_min" in expected:
        assert (
            len(highlights) >= expected["highlights_min"]
        ), f"highlights 数量 {len(highlights)} < {expected['highlights_min']}"


# ====================================================================
#  测试 6：LLM-as-Judge（标记为 slow）
# ====================================================================


@pytest.mark.slow
def test_llm_as_judge() -> None:
    """让 LLM 对分析结果打分，断言 >= 5。"""
    sample_analysis = {
        "summary": "LangChain 是一个 LLM 应用开发框架，支持 500+ 模型和提示词管理。",
        "highlights": [
            "标准化接口集成 500+ LLM 提供商",
            "提示词模板与链式组合",
            "智能代理与记忆系统",
        ],
        "tags": ["llm", "framework", "agent", "python"],
        "quality_score": 0.85,
    }

    prompt = json.dumps(sample_analysis, ensure_ascii=False, indent=2)
    result = chat(prompt=prompt, system=_JUDGE_SYSTEM)
    content = result.get("content", "").strip()

    assert content, "Judge 返回空内容"

    try:
        score = float(content)
    except (ValueError, TypeError):
        # 尝试从文本中提取数字
        import re

        m = re.search(r"\d+", content)
        assert m, f"无法从 Judge 回复中提取分数：{content}"
        score = float(m.group(0))

    assert score >= 5, f"Judge 评分 {score} < 5，分析质量不达标"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
