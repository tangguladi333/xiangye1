from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 自动加载 .env
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path)

_v4_root = str(Path(__file__).resolve().parent.parent)
if _v4_root not in sys.path:
    sys.path.insert(0, _v4_root)

from workflows.model_client import chat

from workflows.security import sanitize_input, filter_output

# 静音底层库日志
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pipeline.model_client").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ====================================================================
#  常量
# ====================================================================

GITHUB_API_URL: str = "https://api.github.com/search/repositories"

_GITHUB_QUERIES: list[str] = [
    "AI agent",
    "LLM framework",
    "LangGraph",
    "RAG",
    "AI tool",
]

_GITHUB_PER_PAGE: int = 5
_QUALITY_THRESHOLD: float = 0.6
_REVIEW_FORCE_PASS_ITERATION: int = 2
_DEFAULT_PROVIDER: str = "deepseek"

# ====================================================================
#  工具函数
# ====================================================================


def extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
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


def chat_json(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    node_name: str = "unknown",
) -> dict:
    result = chat(prompt=prompt, system=system, temperature=temperature, node_name=node_name)
    raw = result.get("content", "")
    parsed = extract_json(raw)
    return {"parsed": parsed, "usage": result.get("usage", {}), "raw": raw}


def accumulate_usage(tracker: dict, usage: dict) -> dict:
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return {
        "total_prompt_tokens": tracker.get("total_prompt_tokens", 0) + prompt,
        "total_completion_tokens": tracker.get("total_completion_tokens", 0) + completion,
        "total_cost_cny": tracker.get("total_cost_cny", 0.0),
        "calls": tracker.get("calls", 0) + 1,
    }


def make_article_id(source_type: str, title: str) -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff-]", "", title)[:20].lower()
    return f"{date_part}-{source_type}-{slug}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_index(articles_dir: str) -> None:
    index_path = os.path.join(articles_dir, "index.json")
    index: list[dict] = []
    pattern = os.path.join(articles_dir, "*.json")
    for fp in sorted(glob.glob(pattern)):
        if fp.endswith("index.json"):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                article = json.load(f)
            index.append({
                "id": article.get("id", ""),
                "title": article.get("title", ""),
                "source_url": article.get("source_url", ""),
                "source_type": article.get("source_type", ""),
                "tags": article.get("tags", []),
                "status": article.get("status", ""),
                "curated_at": article.get("curated_at", ""),
            })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[SaveNode] 跳过索引文件 %s: %s", fp, e)
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("[SaveNode] 写入 index.json 失败: %s", e)
