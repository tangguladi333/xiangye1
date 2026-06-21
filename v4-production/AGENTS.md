# V3 多 Agent 知识库 — AGENTS.md

## 架构

LangGraph 工作流，7 个独立 Agent 各居一文件：

| Agent 文件 | 函数 | 职责 |
|---|---|---|
| `workflows/planner_agent.py` | `planner_agent` | LLM 规划采集主题 |
| `workflows/collector_agent.py` | `collector_agent` | GitHub Search API 采集 |
| `workflows/analyzer_agent.py` | `analyzer_agent` | LLM 分析每条 source |
| `workflows/organizer_agent.py` | `organizer_agent` | 过滤/去重/PII掩码/组装 |
| `workflows/reviewer_agent.py` | `reviewer_agent` | LLM 四维度审核评分 |
| `workflows/reviser_agent.py` | `reviser_agent` | 按审核反馈 LLM 修正 |
| `workflows/human_flag_agent.py` | `human_flag_agent` | 敏感内容标记人工 |
| `workflows/graph.py` | `build_graph` | 编排上述 7 节点 |

### 共享层

- `_shared.py` — 工具函数（chat_json, extract_json, accumulate_usage, security hooks 等）
- `state.py` — 通过 `workflows/state.py` re-export KBState
- `model_client.py` — 通过 `pipeline/model_client.py` re-export chat/get_cost_guard
- `nodes.py` — 向后兼容，将 7 agent 映射为原 5 函数接口

### 状态流转

```
plan → collect → analyze → organize → review
                                         │
                              ┌──────────┴─────────┐
                              │  review_passed?     │
                              ├─ True → human_flag → save → END
                              └─ False → revise → organize → review (loop)
```

### 红线

同根目录 AGENTS.md — 额外追加：

1. **agent 文件不可互相 import** — 通过 state 和 graph.py 协调，Agent 之间只能通过 LangGraph 状态交互
2. **_shared.py 不可引入 agent 逻辑** — 保持纯粹工具函数
3. **sys.path 只在模块顶层插入** — 不要在函数内部动态修改
