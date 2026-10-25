# DeepChoice — AI 驱动的技术选型研究 Agent

DeepChoice 基于 Python/LangGraph：输入一个技术选型问题和候选技术，它会检索多种来源、
比较证据并生成可阅读、可导出的报告。报告区分来源事实、模型推断和未知项；没有充分依据时
保留明确缺口，不编造结论。

> 当前状态（2026-10-26）：本仓库处于恢复线 `precodex/deepseek-adapter`，产品入口为
> `POST /research`。最近一次真实配对（2026-10-22）两臂均未通过当时的正式内容门槛；
> 当前版本还没有新的正式指标。开发与下一步见 [AGENTS](AGENTS.md) 和 [HANDOFF](HANDOFF.md)。

## 能做什么

- 输入研究问题、候选技术、场景与约束；可选前置澄清把模糊需求补成可研究任务。
- 从网页、官方文档、GitHub、arXiv、社区和本地知识库检索，保留来源失败和证据冲突。
- 对来源做规则评分，检测并仲裁冲突，组装证据链，生成带来源编号的条件分析并自审。
- 生成 what/why/how、evidence-first 或对比矩阵三种报告，前端可看进度、检索明细和
  Token/耗时观测，支持 Markdown/PDF 导出。
- 提供运行时取消、SSE 进度流、历史记录和快照查询。

## 快速开始

需要 Python 3.11/3.12 与可用的 DeepSeek、Tavily 凭据（本仓库不提交任何密钥）。
共享虚拟环境位于 `D:\deepchoice-agent\.venv`，但它默认导入的是另一工作树的 editable 包，
**必须显式设置本树 PYTHONPATH**：

```powershell
Set-Location D:\deepchoice-precodex
$env:PYTHONPATH = 'D:\deepchoice-precodex\src;D:\deepchoice-precodex'
$python = 'D:\deepchoice-agent\.venv\Scripts\python.exe'

# 后端（本树入口，127.0.0.1:8100）
& $python -m uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8100

# 新终端：前端
$env:API_BASE = 'http://127.0.0.1:8100'
& $python -m streamlit run frontend/app.py
```

凭据通过环境变量或本地不提交的 env 文件提供（应用启动时会 `load_dotenv()`）；也可使用
`run_service.py` 启动受停止线和进程守卫管理的单次运行（它按路径加载共享凭据，不打印）。
健康检查：`GET http://127.0.0.1:8100/health`。

一次研究的最小请求：

```powershell
$body = @{
  query = '我们是一个 5 人团队，做 B2B SaaS，现有 Django + PostgreSQL，想在 Celery 和 RQ 之间选一个后台任务/定时任务方案。需要能可靠重试、能监控任务状态，并尽量少引入新组件。'
  candidate_techs = @('Celery', 'RQ')
  constraints = @('团队 5 人', '现有 Django + PostgreSQL', '需要可靠重试与任务监控', '尽量少引入新组件')
  sub_questions = @('两者的重试与失败处理机制有什么区别？', '监控和运维成本如何？', '什么情况下应选其中一个？')
  report_format = 'what_why_how'
  language = 'zh'
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8100/research' -ContentType 'application/json' -Body $body
```

返回 `task_id` 后，用 `/research/{task_id}/status`、`/stream`、`/report`、`/annotated`、
`/export` 取结果。

## 配置

| 变量 | 用途与默认 |
|---|---|
| `DS_FLASH_API_KEY` | 所有 LLM 调用；兼容 `FLASH_API_KEY` / `DEEPSEEK_API_KEY` |
| `DS_FLASH_MODEL` / `DS_FLASH_BASE_URL` | 默认 `deepseek-v4-flash` / `https://api.deepseek.com/v1` |
| `TAVILY_API_KEYS` / `TAVILY_API_KEY` | 网页检索；多 key 用逗号分隔，支持轮换与耗尽池 |
| `GITHUB_TOKEN` / `STACKEXCHANGE_API_KEY` | 可选，提高对应来源限额 |
| `LLM_DS_CONCURRENCY` | 冲突扫描并发，默认 80 |
| `PRECODEX_LLM_MAX` / `PRECODEX_TAVILY_MAX` / `PRECODEX_WALL_MAX_S` | 本地运行的停止线，默认 40 / 24 / 900 |
| `LEARNED_DOCS_READONLY` / `RETRIEVAL_CACHE_ENABLED` | 评测时冻结知识库写入与检索缓存 |

旧的 Qwen/DashScope 变量和 `LLM_*`/`PRO_*` 名称已退役，不作为 DeepSeek 的回退凭据。

## 已知限制

- 单用户、可信网络部署：API 未提供认证或任务所有权，运行时为单实例；不要直接暴露公网。
- 引用 `verified` 表示页面可达且词法/引用检查通过，不表示模型推断或部署验证成立。
- 官方文档抓取受大小、期限、重定向和路由限制；页面被拒或抓取失败会如实记录为失败。
- 2026-10-22 的 v12 配对未过正式内容门槛，主要差距在官方/版本化证据覆盖与报告内容；
  当前没有该版本的正式通过率或质量指标。

## 历史基准（归档，非当前成绩）

早期 300 case 混合基准（`benchmarks/cases_eval_300.json`，2026-08-31 终测，150 对比 +
150 开放场景）记录过：Top-1 92.0%（287 可判定）、任务成功率 100%（300/300）、
声明溯源率 93.0%、official_doc 召回 65.6%、端到端 P50 342.1 s / P95 445.3 s、
结构 A 级 99%（297/300，仅确定性结构检查）。这些数字属于当时代码与数据集，
**不代表当前版本**；当前版本的指标需重新采集并注明样本、日期、分母与限制。

## 项目结构

```
src/deepchoice/
├── agents/        # 9 个 LangGraph 节点：分析/适配/检索/评分/冲突/证据链/综合/报告/自审
├── retrievers/    # 6 路检索器与统一来源接口
├── clarify/       # 前置澄清
├── formats/       # 3 种报告格式 + 引用与 PDF
├── server/        # FastAPI（/research 系列 + /clarify + /health），SSE
├── state.py       # ResearchState
└── utils/         # LLM 客户端、BGE-M3 嵌入等
frontend/app.py    # Streamlit 前端
benchmarks/        # 历史 case 与批量工具（归档）
scripts/           # 配对诊断、案例冻结等工具
tests/             # 测试
```

## 文档

- [AGENTS.md](AGENTS.md)：工作方式、目标、运行与安全约定
- [HANDOFF.md](HANDOFF.md)：当前代码身份、真实结果、材料位置与下一步
- [CHANGELOG.md](CHANGELOG.md) / [RETRACTIONS.md](RETRACTIONS.md)：历史变更与已撤回结论

## License

MIT
