# AI Knowledge Base — V4 生产版

多 Agent 协作的 AI 知识采集、分析、推送系统。每天自动从 GitHub Trending 采集 AI/LLM/Agent 开源项目，经过 LLM 分析整理后通过飞书推送日报。

## 架构

```
                    ┌──────────┐
                    │  plan    │  LLM 规划采集主题
                    └────┬─────┘
                         │
                    ┌────▼──────┐
                    │  collect  │  GitHub Search API 采集
                    └────┬──────┘
                         │
                    ┌────▼──────┐
                    │  analyze  │  LLM 结构化分析
                    └────┬──────┘
                         │
                    ┌────▼───────┐
                    │  organize  │  去重/过滤/PII掩码
                    └────┬───────┘
                         │
                    ┌────▼───────┐
                    │   review   │  LLM 四维审核
                    └────┬───────┘
                         │
               ┌─────────┴──────────┐
               │   review_passed?   │
               ├─ True                ├─ False → revise → organize → review
               │                      │
               │               ┌──────▼──────┐
               │               │  human_flag │  敏感内容标记
               │               └──────┬──────┘
               │                      │
               │               ┌──────▼──────┐
               │               │    save     │  写入 JSON + 索引
               │               └──────┬──────┘
               │                      │
               │                 ┌────▼────┐
               └─────────────────►  END   │
                                  └─────────┘
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r ../requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：填入 DEEPSEEK_API_KEY 和 FEISHU_WEBHOOK_URL

# 3. 运行 LangGraph 工作流（需要 DEEPSEEK_API_KEY）
python workflows/graph.py

# 4. 推送飞书日报
python -c "
import asyncio
from distribution.publisher import publish_daily_digest
asyncio.run(publish_daily_digest())
"

# 5. 启动交互式 Bot
python -c "
from bot.knowledge_bot import KnowledgeBot
bot = KnowledgeBot()
resp = bot.handle_message('user_001', '/today')
print(resp.text)
"
```

## 项目结构

```
v4-production/
├── .env.example          # 环境变量模板
├── .gitignore
├── AGENTS.md             # V3 多 Agent 架构说明
├── README.md
├── bot/
│   └── knowledge_bot.py  # 交互式 Bot（搜索/日报/推荐/订阅）
├── distribution/
│   ├── formatter.py      # Markdown + 飞书卡片格式化
│   └── publisher.py      # 飞书 Webhook 异步推送
├── knowledge/            # 数据目录（自动创建）
│   ├── articles/         # 最终知识条目 JSON
│   ├── pending_review/   # 待人工审核
│   └── raw/              # 原始采集数据
├── tests/
│   ├── cost_guard.py     # 预算守卫测试
│   ├── eval_test.py      # 评估测试
│   └── security.py       # 安全测试
├── workflows/
│   ├── _shared.py        # 共享工具函数
│   ├── graph.py          # LangGraph 图编排
│   ├── state.py          # KBState TypedDict
│   ├── model_client.py   # 模型客户端（re-export）
│   ├── security.py       # 输入清洗 + PII 掩码
│   ├── nodes.py          # 向后兼容节点
│   ├── planner_agent.py
│   ├── collector_agent.py
│   ├── analyzer_agent.py
│   ├── organizer_agent.py
│   ├── reviewer_agent.py
│   ├── reviser_agent.py
│   └── human_flag_agent.py
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | ❌ | 默认 `https://api.deepseek.com` |
| `BUDGET_YUAN` | ❌ | 单次运行预算上限（默认 0.5） |
| `FEISHU_WEBHOOK_URL` | ✅ 推送 | 飞书机器人 Webhook |

## 状态流转

每条知识条目的状态流转：`raw` → `analyzed` → `curated` → `distributed`

## 测试

```bash
# 快速测试（跳过 LLM 调用）
pytest tests/eval_test.py -v -m "not slow"

# 完整测试
pytest tests/eval_test.py -v

# 安全组件自测
python tests/security.py

# 预算守卫自测
python tests/cost_guard.py
```
