from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


MAX_INPUT_LENGTH: int = 10000

INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+all\s+previous\s+(instructions|rules|prompts|commands)", re.I),
    re.compile(r"forget\s+(all\s+)?(instructions|rules|prompts|previous)", re.I),
    re.compile(r"override\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"(system|instruction|setup)\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"act\s+as\s+", re.I),
    re.compile(r"disregard\s+(previous|all|the\s+above)", re.I),
    re.compile(r"</?(system|user|assistant)>", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"\|\|im_start\|\|", re.I),
    re.compile(r"忽略.*(指令|规则|限制|要求|设定)"),
    re.compile(r"忘记.*(规则|限制|要求|设定|指令)"),
    re.compile(r"覆盖.*(提示|指令|规则)"),
    re.compile(r"系统提示"),
    re.compile(r"扮演"),
    re.compile(r"作为.*AI(助手|机器人)?"),
    re.compile(r"无视.*(限制|规则|要求)"),
    re.compile(r";\s*(rm|sh|bash|cat|curl|wget)\s+"),
    re.compile(r"\|\s*(cat|sh|bash|curl|wget)\s+"),
    re.compile(r"\$\(.*\)"),
    re.compile(r"`.*`"),
]


def sanitize_input(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    for pattern in INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            warnings.append(f"检测到注入模式: {m.group()[:60]}")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(cleaned) > MAX_INPUT_LENGTH:
        warnings.append(f"输入超长，已截断至 {MAX_INPUT_LENGTH} 字符")
        cleaned = cleaned[:MAX_INPUT_LENGTH]
    return cleaned, warnings


PII_PATTERNS: dict[str, re.Pattern] = {
    "phone": re.compile(r"1[3-9]\d{9}"),
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "id_card": re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
}

_MASK_TEMPLATES: dict[str, str] = {
    "phone": "[PHONE_MASKED]",
    "email": "[EMAIL_MASKED]",
    "id_card": "[ID_CARD_MASKED]",
    "credit_card": "[CREDIT_CARD_MASKED]",
    "ip": "[IP_MASKED]",
}


def filter_output(text: str, mask: bool = True) -> tuple[str, list[dict]]:
    all_matches: list[dict] = []
    for pii_type, pattern in PII_PATTERNS.items():
        for m in pattern.finditer(text):
            all_matches.append({
                "type": pii_type,
                "match": m.group(),
                "pos": m.start(),
                "end": m.end(),
            })
    all_matches.sort(key=lambda x: (x["pos"], -x["end"]))
    unique: list[dict] = []
    for m in all_matches:
        if unique and m["pos"] < unique[-1]["end"]:
            continue
        unique.append(m)
    detections = [{"type": m["type"], "match": m["match"], "pos": m["pos"]} for m in unique]
    if not mask:
        return text, detections
    filtered = text
    for m in reversed(unique):
        start, end = m["pos"], m["end"]
        filtered = filtered[:start] + _MASK_TEMPLATES[m["type"]] + filtered[end:]
    return filtered, detections
