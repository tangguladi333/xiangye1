#!/usr/bin/env python3
"""5-dimension quality scoring for knowledge entry JSON files.

Supports single file and glob pattern input. Each entry is scored across
5 dimensions for a weighted total of 100 points.

Usage:
    python hooks/check_quality.py path/to/file.json
    python hooks/check_quality.py path/to/*.json
    python hooks/check_quality.py file1.json file2.json file3.json

Exit codes:
    0  — no C-grade entries
    1  — at least one C-grade entry
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ================================  常量定义  ================================

# 知识条目 status 字段的合法值集合
VALID_STATUSES: set[str] = {"raw", "analyzed", "curated", "distributed"}

# 用于「摘要质量」加分奖励的技术关键词
TECH_KEYWORDS: set[str] = {
    "llm",
    "agent",
    "rag",
    "ai",
    "大模型",
    "机器学习",
    "深度学习",
    "transformer",
    "neural",
    "embedding",
    "generative",
    "multimodal",
    "nlp",
    "自然语言",
    "知识图谱",
    "vector",
    "检索增强",
}

# 中文空洞词黑名单（命中一个扣 3 分）
EMPTY_WORDS_CN: list[str] = [
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "全链路",
    "底层逻辑",
    "颗粒度",
    "对齐",
    "拉通",
    "沉淀",
    "强大的",
    "革命性的",
]

# 英文空洞词黑名单（不区分大小写，命中一个扣 3 分）
EMPTY_WORDS_EN: list[str] = [
    "groundbreaking",
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "state-of-the-art",
    "bleeding-edge",
    "world-class",
    "best-in-class",
    "next-generation",
]

# 标准标签列表，用于「标签精度」维度的合法校验
VALID_TAGS: set[str] = {
    # Core AI / LLM
    "llm",
    "agent",
    "rag",
    "embeddings",
    "fine-tuning",
    "inference",
    "training",
    "prompt",
    "multimodal",
    "reasoning",
    "nlp",
    "computer-vision",
    "deep-learning",
    "machine-learning",
    # Agent
    "multi-agent",
    "tool-use",
    "function-calling",
    "workflow",
    "mcp",
    "a2a",
    "agentic",
    "orchestration",
    # Infrastructure
    "framework",
    "platform",
    "api",
    "sdk",
    "library",
    "database",
    "storage",
    "memory",
    "search",
    "vector-db",
    # Application
    "application",
    "devtools",
    "automation",
    "coding",
    "chatbot",
    "assistant",
    "copilot",
    "knowledge-base",
    "open-source",
    "production",
    "enterprise",
    # Data
    "data",
    "pipeline",
    "analytics",
    "observability",
    # Vendors / Tools
    "langchain",
    "openai",
    "anthropic",
    "huggingface",
    "pytorch",
    # Categories
    "tutorial",
    "demo",
    "benchmark",
    "evaluation",
    "testing",
    "security",
    "privacy",
    "governance",
    "research",
}

# 报告输出时各维度的显示名称与顺序
DIMENSION_NAMES: list[str] = [
    "摘要质量",
    "技术深度",
    "格式规范",
    "标签精度",
    "空洞词检测",
]


# ================================  数据结构  ================================


@dataclass
class DimensionScore:
    """单个维度的评分结果。

    Attributes:
        name: 维度名称（如"摘要质量"）。
        score: 实际得分。
        max_score: 该维度满分。
        detail: 评分依据的文字说明。
    """

    name: str
    score: float
    max_score: int
    detail: str = ""


@dataclass
class QualityReport:
    """一条知识条目的完整质量报告。

    Attributes:
        entry_id: 条目 ID。
        title: 条目标题。
        file_name: 来源文件名。
        dimensions: 5 个维度的评分结果列表。
    """

    entry_id: str
    title: str
    file_name: str
    dimensions: list[DimensionScore]

    @property
    def total(self) -> float:
        """加权总分 (0-100)。"""
        return sum(d.score for d in self.dimensions)

    @property
    def grade(self) -> str:
        """等第字母：A >= 80, B >= 60, C < 60。"""
        t = self.total
        if t >= 80:
            return "A"
        if t >= 60:
            return "B"
        return "C"


# ============================  维度评分函数  ==============================


def score_summary(item: dict[str, Any]) -> DimensionScore:
    """评估摘要质量 (0-25 分)。

    评分逻辑：
        - >= 50 字：满分 25 分
        - >= 20 字：基本分 15 分
        - < 20 字：0 分
        - 包含技术关键词：额外 +2 分（上限 25 分）

    Args:
        item: 知识条目字典。

    Returns:
        摘要质量维度的评分结果。
    """
    summary = item.get("summary", "")
    if not isinstance(summary, str) or not summary:
        return DimensionScore("摘要质量", 0.0, 25, "缺少摘要")

    length = len(summary)
    if length >= 50:
        base = 25.0
        detail = f"{length}字 (满分)"
    elif length >= 20:
        base = 15.0
        detail = f"{length}字 (基本分)"
    else:
        base = 0.0
        detail = f"{length}字 (不足20字)"

    lower = summary.lower()
    bonus = 2.0 if any(kw.lower() in lower for kw in TECH_KEYWORDS) else 0.0
    if bonus:
        detail += " +技术关键词"

    return DimensionScore("摘要质量", min(base + bonus, 25.0), 25, detail)


def score_depth(item: dict[str, Any]) -> DimensionScore:
    """评估技术深度 (0-25 分)。

    优先使用条目中的 ``score`` 字段（1-10 线性映射到 0-25）。
    若不存在，则回退到 ``maturity.stars`` 按星级分级给分。

    Args:
        item: 知识条目字典。

    Returns:
        技术深度维度的评分结果。
    """
    s = item.get("score")
    if isinstance(s, (int, float)) and 1 <= s <= 10:
        score = round(s / 10.0 * 25, 1)
        return DimensionScore("技术深度", score, 25, f"score={s}")

    # 回退策略：根据 GitHub stars 数量分级评分
    maturity = item.get("maturity")
    if isinstance(maturity, dict):
        stars = maturity.get("stars")
        if isinstance(stars, (int, float)):
            thresholds: list[tuple[int, int]] = [
                (50000, 25),
                (10000, 20),
                (5000, 15),
                (1000, 10),
                (100, 5),
            ]
            for threshold, val in thresholds:
                if stars >= threshold:
                    return DimensionScore(
                        "技术深度", float(val), 25, f"stars>={threshold} -> {val}"
                    )
            return DimensionScore("技术深度", 0.0, 25, f"stars={stars} 过低")

    return DimensionScore("技术深度", 0.0, 25, "缺少score/stars")


def score_format(item: dict[str, Any]) -> DimensionScore:
    """评估格式规范 (0-20 分)。

    检查以下 5 项，每项 4 分：
        1. id 存在且为字符串
        2. title 存在且为字符串
        3. source_url 或 url 存在且为字符串
        4. status 存在且为合法值
        5. collected_at 存在且为字符串

    Args:
        item: 知识条目字典。

    Returns:
        格式规范维度的评分结果。
    """
    score = 0.0
    parts: list[str] = []

    # 1. id 字段检查
    if isinstance(item.get("id"), str):
        score += 4.0
        parts.append("id+4")
    else:
        parts.append("id+0")

    # 2. title 字段检查
    if isinstance(item.get("title"), str):
        score += 4.0
        parts.append("title+4")
    else:
        parts.append("title+0")

    # 3. 来源 URL 检查（兼容新旧两种字段名）
    if isinstance(item.get("source_url"), str) or isinstance(item.get("url"), str):
        score += 4.0
        parts.append("url+4")
    else:
        parts.append("url+0")

    # 4. status 合法值检查
    status = item.get("status")
    if isinstance(status, str) and status in VALID_STATUSES:
        score += 4.0
        parts.append("status+4")
    else:
        parts.append("status+0")

    # 5. 采集时间戳检查
    if isinstance(item.get("collected_at"), str):
        score += 4.0
        parts.append("time+4")
    else:
        parts.append("time+0")

    return DimensionScore("格式规范", score, 20, " ".join(parts))


def score_tags(item: dict[str, Any]) -> DimensionScore:
    """评估标签精度 (0-15 分)。

    评分逻辑：
        - 1-3 个合法标签：15 分（最佳）
        - 4+ 个合法标签：10 分（过多稀释精度）
        - 每个非法标签：-3 分

    Args:
        item: 知识条目字典。

    Returns:
        标签精度维度的评分结果。
    """
    tags = item.get("tags", [])
    if not isinstance(tags, list) or not tags:
        return DimensionScore("标签精度", 0.0, 15, "无标签")

    # 分离合法标签与非法标签
    valid = [t for t in tags if isinstance(t, str) and t in VALID_TAGS]
    invalid = [t for t in tags if isinstance(t, str) and t not in VALID_TAGS]
    invalid += [t for t in tags if not isinstance(t, str)]

    n_valid = len(valid)
    n_invalid = len(invalid)
    base = 15.0 if 1 <= n_valid <= 3 else (10.0 if n_valid >= 4 else 0.0)
    penalty = n_invalid * 3.0
    final = max(base - penalty, 0.0)

    detail_parts: list[str] = []
    if n_valid:
        detail_parts.append(f"{n_valid}合法")
    if n_invalid:
        detail_parts.append(f"{n_invalid}非法(-{int(penalty)})")
    detail = ", ".join(detail_parts) if detail_parts else "无合法标签"

    return DimensionScore("标签精度", final, 15, detail)


def score_empty_words(item: dict[str, Any]) -> DimensionScore:
    """评估空洞词检测 (0-15 分)。

    扫描 title、summary、highlights、use_cases 四个字段，
    检查是否包含中英文空洞词黑名单中的词汇，每个匹配扣 3 分。

    Args:
        item: 知识条目字典。

    Returns:
        空洞词检测维度的评分结果。
    """
    texts: list[str] = []
    if isinstance(item.get("title"), str):
        texts.append(item["title"])
    if isinstance(item.get("summary"), str):
        texts.append(item["summary"])
    for field in ("highlights", "use_cases"):
        val = item.get(field)
        if isinstance(val, list):
            texts.extend(v for v in val if isinstance(v, str))

    combined = " ".join(texts)
    combined_lower = combined.lower()
    matches: list[str] = []

    # 中文空洞词精确匹配
    for word in EMPTY_WORDS_CN:
        if word in combined:
            matches.append(word)
    # 英文空洞词不区分大小写匹配
    for word in EMPTY_WORDS_EN:
        if word in combined_lower:
            matches.append(word)

    penalty = len(matches) * 3.0
    final = max(15.0 - penalty, 0.0)

    if matches:
        detail = f"命中{len(matches)}个({', '.join(matches)}) -{int(penalty)}"
    else:
        detail = "无空洞词"

    return DimensionScore("空洞词检测", final, 15, detail)


# ============================  综合评分入口  ===============================


def check_entry(item: dict[str, Any], file_name: str) -> QualityReport:
    """对单条知识条目执行全部 5 个维度的质量评分。

    Args:
        item: 知识条目字典。
        file_name: 来源文件名（仅用于报告显示）。

    Returns:
        该条目的完整质量报告。
    """
    dims = [
        score_summary(item),
        score_depth(item),
        score_format(item),
        score_tags(item),
        score_empty_words(item),
    ]
    entry_id = str(item.get("id", "?"))
    title = str(item.get("title", "?"))
    return QualityReport(entry_id, title, file_name, dims)


# ==========================  文件解析与抽取  ==============================


def extract_items(data: Any, file_name: str) -> list[tuple[dict[str, Any], str]]:
    """从解析后的 JSON 数据中抽取所有知识条目。

    支持三种顶层结构：
        1. 数组 — 每个元素是一条知识条目
        2. 字典 + items — data["items"] 是条目列表
        3. 单字典 — 字典本身即为一条知识条目

    Args:
        data: json.loads 解析后的 Python 对象。
        file_name: 来源文件名。

    Returns:
        (条目字典, 位置提示) 元组的列表。
    """
    items: list[tuple[dict[str, Any], str]] = []

    if isinstance(data, list):
        # 情况 1：顶层是数组，逐元素判断是否为字典
        for i, item in enumerate(data):
            if isinstance(item, dict):
                items.append((item, f"{file_name}[{i}]"))
    elif isinstance(data, dict):
        # 情况 2 或 3：顶层是对象
        if "items" in data and isinstance(data["items"], list):
            # data.items 为条目列表（采集器/分析器输出格式）
            for i, item in enumerate(data["items"]):
                if isinstance(item, dict):
                    items.append((item, f"{file_name}.items[{i}]"))
        else:
            # 单条目文件（整理后归档格式）
            items.append((data, file_name))

    return items


def process_file(path: Path) -> tuple[list[QualityReport], list[str]]:
    """读取并解析单个 JSON 文件，对所有条目评分。

    Args:
        path: JSON 文件路径。

    Returns:
        (报告列表, 错误信息列表) 的二元组。
        错误列表为空表示文件处理成功。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        return [], [f"读取失败 {path.name}: {e}"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], [f"JSON解析错误 {path.name}: {e}"]

    reports: list[QualityReport] = []
    for item, _hint in extract_items(data, path.name):
        report = check_entry(item, path.name)
        reports.append(report)
    return reports, []


# ============================  输出与 UI  =================================


def print_progress(current: int, total: int) -> None:
    """在终端打印行内进度条。

    使用回车符 \\r 实现单行动态刷新，不换行。
    进度条宽度固定为 30 个字符。

    Args:
        current: 当前已处理的条目数。
        total: 待处理的总条目数。
    """
    bar_width = 30
    if total == 0:
        return
    filled = int(bar_width * current / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    pct = int(100 * current / total)
    sys.stdout.write(f"\r  进度: [{bar}] {pct}% ({current}/{total})")
    sys.stdout.flush()


def print_report(reports: list[QualityReport]) -> None:
    """打印完整的质量评分报告。

    按条目逐个输出各维度得分、条形图与评分依据，
    末尾输出汇总统计（A/B/C 等级分布与平均分）。

    Args:
        reports: 所有条目的质量报告列表。
    """
    sep = "─" * 54
    print("\n\n" + "=" * 60)
    print("  知识条目质量评分报告")
    print("=" * 60)

    grade_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    max_width = max(len(name) for name in DIMENSION_NAMES)

    for i, r in enumerate(reports):
        print(f"\n  [{i + 1}] {r.file_name}  |  {r.entry_id}  {r.title}")
        print(f"  {sep}")
        for dim in r.dimensions:
            pct = dim.score / dim.max_score * 100 if dim.max_score > 0 else 0.0
            bar_len = max(1, int(pct / 10))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            print(
                f"  {dim.name:<{max_width}}  "
                f"{dim.score:>5.1f}/{dim.max_score:<2d}  "
                f"{bar}  {dim.detail}"
            )
        print(f"  {sep}")
        total_str = f"总分: {r.total:5.1f}/{sum(d.max_score for d in r.dimensions)}"
        print(f"  {total_str}  等级: {r.grade}")
        grade_counts[r.grade] += 1

    # 汇总统计
    print(f"\n{'=' * 60}")
    print("  汇总")
    print(f"  {'=' * 60}")
    print(f"  总条目:     {len(reports)}")
    for g in ("A", "B", "C"):
        print(f"  {g}级:       {grade_counts[g]}")
    if reports:
        avg = sum(r.total for r in reports) / len(reports)
        print(f"  平均分:     {avg:.1f}")
    print(f"  {'=' * 60}")


# ============================  CLI 入口  ==================================


def main() -> None:
    """CLI 入口：解析参数、处理文件、打印报告、设置退出码。

    退出码语义：
        0 — 所有条目均 >= C 级（无 C 级条目）
        1 — 存在至少一条 C 级条目
    """
    if len(sys.argv) < 2:
        print("用法: python hooks/check_quality.py <json_file> [json_file2 ...]")
        print("示例: python hooks/check_quality.py knowledge/articles/*.json")
        sys.exit(1)

    # 展开文件路径列表（支持显式路径与通配符模式混用）
    paths: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            expanded = sorted(p.glob("*.json"))
            if not expanded:
                print(f"错误: 目录中未找到 JSON 文件: {arg}", file=sys.stderr)
                sys.exit(1)
            paths.extend(expanded)
        elif p.exists():
            # 直接存在的文件路径
            paths.append(p)
        else:
            # 尝试用通配符展开
            expanded = sorted(Path().glob(arg))
            if not expanded:
                print(f"错误: 未找到匹配路径: {arg}", file=sys.stderr)
                sys.exit(1)
            paths.extend(expanded)

    if not paths:
        print("错误: 没有可处理的文件", file=sys.stderr)
        sys.exit(1)

    # 预扫描：统计总条目数用于进度条展示
    total_entries = 0
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            for _item, _hint in extract_items(data, path.name):
                total_entries += 1
        except Exception:
            pass

    all_reports: list[QualityReport] = []
    processed = 0
    for path in paths:
        reports, errors = process_file(path)
        for err in errors:
            print(f"\n[错误] {err}")
        all_reports.extend(reports)
        processed += len(reports)
        print_progress(processed, total_entries)

    print_report(all_reports)

    has_c = any(r.grade == "C" for r in all_reports)
    if has_c:
        sys.exit(1)


if __name__ == "__main__":
    main()
