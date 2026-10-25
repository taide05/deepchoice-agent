# DeepChoice 开发工作指南

更新：2026-10-26。本文件说明在本工作树如何开发；用户最新要求优先，历史文档不自动成为任务。

## 工作区与代码身份

- 唯一开发目标是本工作树 `D:\deepchoice-precodex`，分支 `precodex/deepseek-adapter`。
  接续代码基点为 `b080213`；历史恢复起点 `48b32bd` 只用于追溯，不 reset、不删除后续成果。
- 其他工作树只读保留，不沿用其规则、运行契约或测试要求：
  `D:\deepchoice-agent`（已放弃的 durable 线）、`D:\deepchoice-dsh`（旧工作树与历史材料库）。
  其中 `7da3701`、`ae5f3f3`、`r10_round2` 等材料是否参考由用户与 dsh 决定，不自动移植。
- DSH 会话默认目录可能不在本树：所有代码编辑、Git、测试和服务命令都显式指定本工作树；
  共享解释器每次显式设置本树源码路径（见“运行入口”）。

## 当前目标

1. 先跑出**一份可展示、有依据的技术选型报告**：回答原问题，依据适用，条件和缺口明确。
2. 再让链路能**稳定产出**这种报告。
3. 之后才做小样本真实指标与展示材料。历史数字不是当前版本的成绩。

质量按实际报告内容判断，不看结构分、引用条数、测试数量或字段齐全率。未核验的信息不冒充
已核实；可以给有来源的条件性建议，不能编造支持，也不能为单个案例硬编码答案或来源。

## 开发方式

- 现有 9 节点研究链（分析→适配→检索→评分→冲突→证据链→综合→报告→自审）是产品设计，
  不要求简化或合并。先定位真实问题出在哪一层，再做最小修改。
- 优先用已保存的真实报告和运行材料离线回放定位；普通改动跑相关测试并检查实际输出，
  涉及运行时/持久化等较大改动再跑全套。历史 668 项测试记录只作参考，不是每步门槛。
- 不新增没有用户的框架、观测、门禁或流程；不把一次失败直接变成新分支或新规则。
- 可以调整提示、证据选择、分析容量与报告结构，修改前核对实际消费者和用户可见输出。
- 真实运行本阶段可直接进行（用户已同意多跑）：记录版本、时间与实际用量，费用按实，
  不虚构。单次默认沿用 `run_limits.py` 的 40 LLM / 24 Tavily / 900 s 停止线，必要时用
  `PRECODEX_LLM_MAX`、`PRECODEX_TAVILY_MAX`、`PRECODEX_WALL_MAX_S` 调整并写入记录。
- 运行/评测案例按项目实际输入方式重新设计（简短真实问题 + 必要场景与约束，让前置澄清和
  检索能消化）；不把 Codex 时期过度细节化的案例当作新验收标准，旧题只作开发回归。

## 安全、数据与 Git

- 不打印、不提交、不外传密钥；只读取运行必需的最小环境信息。
- 保留 `.env`、`learned_docs.json`、`outputs/`、数据库、缓存、stash、历史报告和未跟踪材料。
  不 reset/restore/stash drop/amend/rebase/强推，不删除其他工作树内容。
- 提交用显式路径，只提交本次改动；push、发布和历史重写只在用户明确要求时执行。
- 外呼走既有 outbound/安全抓取；报告 HTML/PDF 保留现有 sanitizer。

## 运行入口

- 产品入口是 `/research`（不是 durable `/api/v1/tasks`）；前端是 `frontend/app.py`（Streamlit）。
- 解释器：`D:\deepchoice-agent\.venv\Scripts\python.exe`（Python 3.12.4）。
- 每个进程显式设置：
  `Set-Location D:\deepchoice-precodex`
  `$env:PYTHONPATH = 'D:\deepchoice-precodex\src;D:\deepchoice-precodex'`
- 后端：`python -m uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8100`
- 前端：`$env:API_BASE='http://127.0.0.1:8100'` 后 `python -m streamlit run frontend/app.py`
- 受停止线和进程守卫管理的本地运行可用 `run_service.py`（加载共享凭据文件，不打印）。
- 测试：`python -m pytest <相关文件> -q -p no:cacheprovider`；临时文件写本树 `.scratch/`。

## 文档

- 活动文档只有三份：本文件（工作方式）、`HANDOFF.md`（当前状态与下一步）、
  `README.md`（产品与运行说明）。三者不重复维护同一份信息。
- `CHANGELOG.md`、`RETRACTIONS.md`、`fix_pack_*.md`、`run_record*.md`、`template-*`、
  `local_cleanup_archive/`、`.scratch/` 是历史记录或本地材料，不是当前任务清单。
- 会话交接、临时计划、调试日志放 `.scratch/`，不提交。
