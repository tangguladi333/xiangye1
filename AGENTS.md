# AI Knowledge Base — AGENTS.md

## 项目概述

AI 知识库助手自动从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的技术动态，通过国产大模型进行结构化分析，产出统一格式的知识条目 JSON，并通过 Telegram / 飞书等多渠道分发给用户。

## 技术栈

| 层级 | 选型 |
|---|---|
| 语言 | Python 3.12 |
| Agent 框架 | LangGraph |
| 爬虫框架 | OpenClaw |
| AI 调用 | OpenCode + 国产大模型 |
| 数据存储 | 本地 JSON 文件 |
| 分发 | Telegram Bot / 飞书 Bot |

## 编码规范

### 通用

| 条目 | 规范 |
|---|---|
| Python 格式化 | Black 行宽 88 + `ruff` lint，`pyproject.toml` 统一配置 |
| TypeScript | `tsconfig.json` 中开启 `strict: true` |
| 命名 | `snake_case`（变量、函数、模块）、`UPPER_CASE`（常量）、`PascalCase`（类） |
| 类型注解 | 所有函数参数和返回值必须标注类型 |
| Docstring | Google 风格；公开函数必须有，非公开函数不加 |
| 日志 | 禁止裸 `print()`，统一 `logging.getLogger(__name__)` |
| 异常 | 自定义异常继承 `AppError`，禁止 `except: pass` |
| 魔法字符串 | 模块级共享常量抽 `UPPER_CASE`，函数内局部字面量不强制 |
| 提交规范 | 不允许 `TODO`/`FIXME`/`HACK` 提交到 `main`，CI 中 `grep -rn` 拦截 `src/` |

### 测试

- 框架：pytest，测试文件与源文件保持镜像结构
- 覆盖率：整体 ≥ 80%，增量 ≥ 80%

### CI 工具链

`black --check` + `ruff check` + `mypy src/` + `pytest --cov`，统一在 `pyproject.toml` 中配置。

## 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/           # Agent 定义（采集/分析/整理）
│   ├── skills/           # 可复用技能（解析/格式化/分发）
│   └── rules/            # 权限与安全规则
├── config/
│   └── settings.py       # 全局配置（源URL/Api key/渠道Token）
├── knowledge/
│   ├── raw/              # 采集原始数据（按日期分目录）
│   └── articles/         # 结构化知识条目 JSON（最终产物）
├── src/
│   ├── collector/        # 采集模块（OpenClaw Spider）
│   ├── analyzer/         # 分析模块（LLM Agent）
│   ├── curator/          # 整理模块（去重/打标签/归档）
│   └── distributor/      # 分发模块（Telegram/飞书 adapter）
├── tests/
├── AGENTS.md
├── pyproject.toml
└── requirements.txt
```

## 知识条目 JSON 格式

```json
{
  "id": "20260613-001",
  "title": "Repo 或文章标题",
  "source_url": "https://github.com/owner/repo",
  "source_type": "github_trending | hacker_news",
  "summary": "AI 生成的摘要（中文，100 字以内）",
  "highlights": ["亮点1", "亮点2"],
  "use_cases": ["适用场景1"],
  "maturity": {
    "stars": 1200,
    "last_updated": "2026-06-01",
    "production_ready": false
  },
  "tags": ["llm", "agent", "rag"],
  "status": "raw | analyzed | curated | distributed",
  "collected_at": "2026-06-13T08:00:00Z",
  "analyzed_at": "2026-06-13T08:05:00Z"
}
```

`status` 流转：`raw` → `analyzed` → `curated` → `distributed`

## Agent 角色概览

| 角色 | 职责 | 输入 | 输出 | 工具 |
|---|---|---|---|---|
| **采集者 (Collector)** | 定时爬取 GitHub Trending / Hacker News，解析列表页 | 源 URL + 白名单话题 | `knowledge/raw/{date}.json` | OpenClaw Spider + Requests |
| **分析者 (Analyzer)** | 对每条 raw 条目调用国产大模型，生成结构化分析 | `raw` JSON → Prompt | 带 `summary/highlights/use_cases/maturity` 的 JSON | OpenCode + LangGraph Chain |
| **整理者 (Curator)** | 去重、标签规范化、归档到 `articles/`、触发分发 | 分析后的条目 | `knowledge/articles/{date}.json` + 分发 payload | 本地文件 I/O + 分发 adapter |

## 红线

以下操作**绝对禁止**，违反视为严重事故：

1. **不审核直接分发** — 所有条目必须先经过 `analyzed` → `curated` 状态流转，不得从 `raw` 直接跳到分发
2. **硬编码密钥** — API Key、Bot Token 等敏感信息必须从环境变量或 `config/settings.py` 读取，禁止写死在代码里
3. **异常静默** — 不允许 `except: pass` 或空 `except`；采集 / 分析 / 分发失败必须记录错误日志并向上冒泡
4. **并发失控** — 爬虫和 LLM 调用必须限制并发数（OpenClaw 配置 `CONCURRENT_REQUESTS=5`，LLM 调用串行或限流）
5. **污染输出** — 禁止将未经 JSON schema 校验的内容写入 `knowledge/articles/`，写入前必须用 pydantic 或 `jsonschema` 校验
6. **跨角色越权** — Agent 角色严格分离，采集者不调用 LLM，分析者不直接写 articles 目录，整理者不再爬取
