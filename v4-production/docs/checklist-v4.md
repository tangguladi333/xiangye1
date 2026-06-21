# V4 上线 Checklist

## 前置条件

- [ ] Python 3.12+ 已安装
- [ ] `pip install -r ../requirements.txt` 已执行

## 环境变量

- [ ] `.env` 已从 `.env.example` 复制
- [ ] `DEEPSEEK_API_KEY` 已填入有效密钥
- [ ] `FEISHU_WEBHOOK_URL` 已填入飞书机器人地址（如需推送）
- [ ] `BUDGET_YUAN` 已设置（建议 0.5~2.0）
- [ ] `.env` 不在 Git 跟踪中（被 `.gitignore` 排除）

## 依赖检查

- [ ] `httpx`、`aiohttp`、`python-dotenv` 已安装
- [ ] `langgraph` 已安装
- [ ] `pytest` 已安装（如需测试）

## 代码检查

- [ ] `python -c "from workflows.graph import build_graph; print('OK')"` 无报错
- [ ] `python -c "from bot.knowledge_bot import KnowledgeBot; print('OK')"` 无报错
- [ ] `python -c "from distribution.publisher import FeishuPublisher; print('OK')"` 无报错

## 测试

- [ ] `python tests/security.py` 全部通过
- [ ] `python tests/cost_guard.py` 全部通过
- [ ] `pytest tests/eval_test.py -v -m "not slow"` 全部通过

## 冒烟测试

- [ ] `python workflows/graph.py` 正常启动（计划阶段需要 API Key）
- [ ] 飞书 Webhook 推送测试：`python -c "import asyncio; from distribution.publisher import FeishuPublisher; asyncio.run(FeishuPublisher().send_message({'title':'Test','summary':'smoke test','source_type':'github_trending','tags':['test'],'maturity':{'stars':0}}))"` 返回 success

## GitHub Actions

- [ ] GitHub 仓库中已配置 `DEEPSEEK_API_KEY` Secret
- [ ] GitHub 仓库中已配置 `FEISHU_WEBHOOK_URL` Secret（如需自动推送）
- [ ] `daily-collect-v4.yml` 已推送到 `main` 分支
- [ ] 可以手动触发 Workflow（`workflow_dispatch`）并跑通

## 截图（用户自行操作）

- [ ] 飞书群聊收到日报的截图
- [ ] GitHub Actions 成功执行的截图
- [ ] 本地 `python workflows/graph.py` 执行输出的截图
