#!/usr/bin/env python3
"""Validate knowledge entry JSON files for schema compliance.

支持单文件或多文件批量校验（通配符 *.json 自动展开）。

用法:
    python hooks/validate_json.py path/to/file.json
    python hooks/validate_json.py path/to/*.json
    python hooks/validate_json.py file1.json file2.json file3.json

退出码:
    0  — 全部文件校验通过
    1  — 存在至少一个校验错误
"""

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 校验规则常量
# ---------------------------------------------------------------------------

# 必填字段定义: {字段名: 期望类型}
# 校验器会依次检查字段是否存在、类型是否匹配。
REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "tags": list,
    "status": str,
}

# status 字段的合法值集合
VALID_STATUSES = {"raw", "analyzed", "curated", "distributed", "draft"}

# audience 字段（可选）的合法值集合
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

# id 格式:
#   1. {YYYYMMDD}-{source_type}-{NNN}  (如 20260617-github_trending-004)
#   2. {YYYYMMDD}-{NNN}                 (如 20260615-005, 旧格式兼容)
#   3. {source}-{YYYYMMDD}-{NNN}        (如 github-20260617-001, 测试文件)
ID_PATTERN = re.compile(
    r"^(?:\d{8}(?:-[a-z_]+)?-\d{3}"  # YYYYMMDD-source-NNN or YYYYMMDD-NNN
    r"|[a-z]+-\d{8}-\d{3}"  # source-YYYYMMDD-NNN (test files)
    r"|\d{8}-[a-z_]+-[a-z0-9-]+)$"  # YYYYMMDD-source-slug (V3 format)
)

# URL 必须以 http:// 或 https:// 开头
URL_PATTERN = re.compile(r"^https?://")


# ---------------------------------------------------------------------------
# 单条目校验
# ---------------------------------------------------------------------------


def validate_item(item: dict, path_hint: str) -> list[str]:
    """校验单条知识条目的所有字段。

    Args:
        item:      待校验的知识条目字典。
        path_hint: 用于错误提示的路径标识，如 "file.json[2]" 或 "file.json.items[2]"。

    Returns:
        错误信息字符串列表；列表为空表示校验通过。
    """
    errors: list[str] = []

    # ---------- 必填字段的存在性与类型校验 ----------
    # 兼容旧格式: source_url 缺失时回退到 url 字段
    for field, expected_type in REQUIRED_FIELDS.items():
        if field == "source_url":
            value = item.get("source_url") or item.get("url")
            if value is None:
                errors.append(f"  [{path_hint}] 缺少必填字段: source_url (或 url)")
                continue
            if not isinstance(value, expected_type):
                errors.append(
                    f"  [{path_hint}] 字段 {field} 类型错误: "
                    f"期望 {expected_type.__name__}, 实际 {type(value).__name__}"
                )
            continue
        if field not in item:
            errors.append(f"  [{path_hint}] 缺少必填字段: {field}")
            continue
        if not isinstance(item[field], expected_type):
            errors.append(
                f"  [{path_hint}] 字段 {field} 类型错误: "
                f"期望 {expected_type.__name__}, 实际 {type(item[field]).__name__}"
            )

    # ---------- id 格式校验 ----------
    # 支持三种格式:
    #   1. {YYYYMMDD}-{source_type}-{NNN}  (新格式, 含 source)
    #   2. {YYYYMMDD}-{NNN}                 (旧格式, 无 source)
    #   3. {source}-{YYYYMMDD}-{NNN}        (测试文件格式)
    if "id" in item and isinstance(item["id"], str):
        if not ID_PATTERN.match(item["id"]):
            errors.append(
                f"  [{path_hint}] id 格式错误: '{item['id']}' — "
                f"期望格式 {{YYYYMMDD}}-[{{source}}]-{{NNN}}"
            )

    # ---------- status 合法值校验 ----------
    # status 必须为 draft / review / published / archived 之一。
    if "status" in item and isinstance(item["status"], str):
        if item["status"] not in VALID_STATUSES:
            errors.append(
                f"  [{path_hint}] status 无效: '{item['status']}' — "
                f"必须为 {', '.join(sorted(VALID_STATUSES))}"
            )

    # ---------- source_url 格式校验 ----------
    # URL 必须以 http:// 或 https:// 开头（不允许相对路径或空值）。
    if (
        "source_url" in item
        and isinstance(item["source_url"], str)
        and item["source_url"]
    ):
        if not URL_PATTERN.match(item["source_url"]):
            errors.append(
                f"  [{path_hint}] source_url 格式错误: "
                f"'{item['source_url'][:80]}...' — "
                f"必须以 http:// 或 https:// 开头"
            )

    # ---------- summary 最小长度校验 ----------
    # 摘要至少 20 个字符（中英文均按字符数计算）。
    if "summary" in item and isinstance(item["summary"], str):
        if len(item["summary"]) < 20:
            errors.append(
                f"  [{path_hint}] summary 过短: {len(item['summary'])} 字 "
                f"— 至少 20 字"
            )

    # ---------- tags 最小数量校验 ----------
    # tags 数组至少包含 1 个标签，不允许空数组。
    if "tags" in item and isinstance(item["tags"], list):
        if len(item["tags"]) < 1:
            errors.append(f"  [{path_hint}] tags 为空 — 至少 1 个标签")

    # ---------- score 可选字段校验 ----------
    # score 存在时，必须为数值类型且在 1-10 范围内。
    if "score" in item:
        score = item["score"]
        if not isinstance(score, (int, float)):
            errors.append(
                f"  [{path_hint}] score 类型错误: 期望 int/float, "
                f"实际 {type(score).__name__}"
            )
        elif not (1 <= score <= 10):
            errors.append(f"  [{path_hint}] score 超出范围: {score} — 必须在 1-10 之间")

    # ---------- audience 可选字段校验 ----------
    # audience 存在时，必须为 beginner / intermediate / advanced 之一。
    if "audience" in item:
        audience = item["audience"]
        if not isinstance(audience, str):
            errors.append(
                f"  [{path_hint}] audience 类型错误: 期望 str, "
                f"实际 {type(audience).__name__}"
            )
        elif audience not in VALID_AUDIENCES:
            errors.append(
                f"  [{path_hint}] audience 无效: '{audience}' — "
                f"必须为 {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


# ---------------------------------------------------------------------------
# 文件级校验
# ---------------------------------------------------------------------------


def validate_file(path: Path) -> list[str]:
    """读取并校验单个 JSON 文件。

    支持三种顶层结构:
    1. 数组         — 每条元素为知识条目
    2. 字典 + items  — data["items"] 为条目列表
    3. 单对象       — 文件本身即为一条知识条目

    Args:
        path: 待校验的 JSON 文件路径。

    Returns:
        错误信息字符串列表；列表为空表示校验通过。
    """
    errors: list[str] = []

    # 读取文件内容
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"  [读取失败] {path.name}: {e}")
        return errors

    # 解析 JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(f"  [JSON解析错误] {path.name}: {e}")
        return errors

    # 根据顶层结构提取待校验记录
    #   - 顶层为 list: 每条元素都是一条知识条目
    #   - 顶层为 dict + items: data["items"] 是条目列表（如采集器的原始输出）
    #   - 顶层为 dict 且无 items: 文件本身就是一条知识条目
    records: list[tuple[dict, str]] = []

    if isinstance(data, list):
        # 情况 1: 顶层是数组
        for i, item in enumerate(data):
            if isinstance(item, dict):
                records.append((item, f"{path.name}[{i}]"))
            else:
                errors.append(
                    f"  [{path.name}[{i}]] 条目不是对象: {type(item).__name__}"
                )

    elif isinstance(data, dict):
        # 情况 2 或 3: 顶层是对象
        if "items" in data and isinstance(data["items"], list):
            # data.items 是条目列表
            for i, item in enumerate(data["items"]):
                if isinstance(item, dict):
                    records.append((item, f"{path.name}.items[{i}]"))
                else:
                    errors.append(
                        f"  [{path.name}.items[{i}]] 条目不是对象: "
                        f"{type(item).__name__}"
                    )
        else:
            # 单条目文件，直接校验
            records.append((data, path.name))

    else:
        errors.append(
            f"  [{path.name}] 顶层结构无效: 期望 array 或 object, "
            f"实际 {type(data).__name__}"
        )

    # 逐条校验
    for item, hint in records:
        errors.extend(validate_item(item, hint))

    return errors


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI 入口: 接收文件路径列表，批量校验后输出结果并设置退出码。"""
    # 检查参数
    if len(sys.argv) < 2:
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        print("示例: python hooks/validate_json.py knowledge/articles/*.json")
        sys.exit(1)

    # 展开参数中的通配符，收集所有待校验文件
    # 支持:
    #   - 显式文件路径   python validate.py a.json b.json
    #   - 通配符        python validate.py "knowledge/articles/*.json"
    #   - 混合两种模式
    paths: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.exists():
            # 直接存在的路径
            paths.append(p)
        else:
            # 可能是通配符模式，尝试 glob 展开
            expanded = sorted(Path().glob(arg))
            if not expanded:
                print(f"错误: 未找到匹配路径: {arg}", file=sys.stderr)
                sys.exit(1)
            paths.extend(expanded)

    # 逐文件校验，收集所有错误
    total_files = len(paths)
    total_errors = 0
    file_errors = 0
    all_errors: list[tuple[str, list[str]]] = []

    for path in paths:
        errs = validate_file(path)
        if errs:
            file_errors += 1
            total_errors += len(errs)
            all_errors.append((path.name, errs))

    # 输出结果
    if all_errors:
        # ---- 有错误: 打印详情 + 汇总，exit 1 ----
        print(f"\n{'=' * 60}")
        print(f"校验失败: {file_errors}/{total_files} 个文件包含错误")
        print(f"{'=' * 60}\n")
        for name, errs in all_errors:
            print(f"文件: {name}")
            for e in errs:
                print(e)
            print()
        print(f"{'=' * 60}")
        print(
            f"总计: {total_files} 个文件, {file_errors} 个文件有错误, "
            f"{total_errors} 条错误"
        )
        print(f"{'=' * 60}")
        sys.exit(1)

    # ---- 全部通过: exit 0 ----
    print(f"✅ 全部通过: {total_files} 个文件, 0 个错误")
    sys.exit(0)


if __name__ == "__main__":
    main()
