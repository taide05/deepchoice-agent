# DeepChoice Agent Guide

更新：2026-10-24。适用于整个仓库。当前工作由用户与 dsh 直接推进。

## 当前执行方式

- 首要目标是尽快把这个个人技术选型项目修到可用、可展示，并形成真实的项目指标。后续目标、路线、样本量和交付标准由用户与 dsh 决定，无需 Codex 审批。
- 接手先看 Git 状态及 [交接](docs/next-session-product-optimization-handoff.md)。只在需要时读相关技术文档，不必逐次通读路线、复盘、审计和历史记录。
- 在用户已委托的范围及预算内连续完成实现、调试、复测和本地提交。正常实现选择、开发失败、阶段切换不要求再次确认；遇到实际预算耗尽、不可逆操作或范围明显变化再集中说明。
- 旧的十轮/八轮/十小时窗口、单例后才能校准、11/12 晋级、每包仅一份全新题、失败后必须等下一轮等流程不再是默认约束。历史额度和失败记录仍照实保留，不当作新额度。
- 开发可以复用失败题、固定材料、重复运行和小批量比较。记录版本及用量即可，不需要每次独立准备者、盲评、seal 或完整 manifest 仪式。若对外声称未见集成绩，才保持对应数据隔离和可核对身份。
- 优先修影响实际回答的问题。删除重复过滤、简化表示、调整提示、局部重构或必要新增均可；不需要先完成全仓审计，也不以删代码数量为目标。
- 提示、分析行上限、事实选择、引用校准、自审和报告格式都是可以改进的实现，不是不可修改的永久产品要求。改变时核对消费者和实际输出，不靠把 unknown 改成 verified 或硬编码案例答案制造效果。
- 验证按风险选择：普通改动跑相关测试并检查实际报告；较大集成、运行时/持久化/安全改动或发布候选再安排全套。独立复核优先用于高风险或确有争议的修改，不要求每包、多轮或纯文档修改都复核。
- 相关回归应能发现真实故障，不为每个低风险文字变化堆测试。保留有独立价值的负例；未跑全套就写明，不冒称全套通过。CI 现有检查仍按实际配置执行。
- 文档跟随实现，更新受影响的入口即可；不要一项修改复制到多份状态、路线、交接和日志。演示、README 和求职材料可与开发并行准备，实际成绩和限制如实表述。
- 汇报以可用报告、解决的用户问题和下一步为主。估算是估算，不把等待用户消息的时间算作主动工时，不为计时补记反复返工。

本节替代历史文档中的执行方式和审批规则。技术契约描述当前程序行为；历史 Phase、OPEN、
停止条件及旧聊天计划不构成新的任务。最新用户指令优先。

## Git 与本地数据

- 开始任务运行 `git status --short --branch`，核对分支及 HEAD；保留用户修改。
- 不擅自 reset、restore、stash、amend、rebase 或覆盖他人改动。完成的改动以聚焦本地提交交接。
- `learned_docs.json`、`.env`、outputs、数据库、缓存、历史报告和 stash 按其原状保留；不要将它们顺手清理或批量暂存。
- push、合并发布分支、release 或历史重写按用户明确要求执行。发布前检查实际待推送提交范围中的密钥、个人材料和无关生成物；后续删除不能移除早期提交中的内容。
- 仅为判断远端状态或发布而刷新 refs；没有刷新就不宣称远端已同步。
- 多工作树不等于同一实现。按差异集成需要的改动，避免整树覆盖和共享 Git 配置变更。

## 必要的实现边界

这些边界保护数据、真实结果和实际费用，不是额外产品验收关卡：

- 默认产品入口为 `/api/v1/tasks/*`。实验树旧接口的结果单独记录，不能冒称当前产品已验证。
- 任务状态、结果和事件通过既有 repository/transaction 写入；保留 CAS、lease/fencing、取消与恢复正确性。产品库与 checkpoint 库分别存储、配对备份；不要用私有 checkpoint 表推断产品任务状态。
- 已提交迁移采用向前追加。修改生命周期、兼容身份或恢复行为时覆盖对应故障路径；无需为不相关的提示或展示修改重做全部运行时验收。
- 已冻结 run 身份和预算按原口径执行；新配置用于新运行。批次额度在同一授权下跨重启累计，未知提交先对账，不能换目录或 ledger 重置已用额度。
- 外呼经既有 outbound 与安全 fetch；保留 URL/DNS/IP/重定向验证、大小与期限限制。保护秘密和用户输入，不记录原始密钥、完整 prompt/response 或敏感异常。
- LLM 使用现有 `utils/llm.py` 以保留重试、预算和用量记录。默认 DeepSeek Flash；旧 Qwen/PRO 凭据不能作为隐式回退。更换模型或供应商依用户与 dsh 的当前方案显式配置。
- 无法确认的来源或用量保持 unknown。词法引用通过不等于语义正确；推断与来源事实区分。报告 HTML/PDF 保留 sanitizer，不把不可信正文直接作为 HTML 执行。
- 当前 SQLite 运行时为单实例、单 worker；API 是单用户可信网络部署，未提供认证/任务所有权。不要以关闭保护来获得并发或公网部署能力。

详细实现按需见 [运行契约](docs/phase1-runtime-contract.md)、代码和测试。它们不是必须重新执行
Phase 1–6 的任务清单。产品逻辑可演进，真实数据和安全边界随相应实现保持正确。

## 常用入口

| 内容 | 路径 |
|---|---|
| API | `src/deepchoice/server/app.py` |
| durable 服务、运行时、持久化 | `src/deepchoice/services/tasks.py`、`src/deepchoice/runtime/`、`src/deepchoice/persistence/` |
| 研究图和节点 | `src/deepchoice/agents/orchestrator.py`、`src/deepchoice/agents/` |
| 来源、外呼 | `src/deepchoice/retrievers/`、`src/deepchoice/outbound/` |
| 共享状态、报告 | `src/deepchoice/state.py`、`src/deepchoice/formats/` |
| UI、评测、测试 | `frontend/app.py`、`benchmarks/`、`tests/` |

使用项目 Python 3.11/3.12 venv；依赖以 `pyproject.toml` 为准。

```powershell
.\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
.\.venv\Scripts\python.exe -m pytest tests/path_to_test.py -q -p no:cacheprovider
# 在需要完整验证时运行：
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.codex-test-tmp
```

配置说明见 [README](README.md)。不要输出 `.env` 值。新增配置同时核对默认值、测试和实际部署
配置，避免文档与运行参数不同。健康检查可能外呼，按需要使用并计入当前额度，不机械重复。

## 评测与文档

- 开发回归、演示、未见评测分别标明用途；旧题可用于前两者。正式结果保留实际分母、版本、失败和评审方式。
- 样本量、阈值、复评比例和基线计划按用户与 dsh 的当前选择执行。旧 120 题、11/12 等计划不是所有开发和展示工作的前置门槛，也不因解除旧流程就变成已通过。
- 当前目录入口见 [docs/README](docs/README.md)。历史报告、300-case 指标和 smoke 结果保留各自日期和数据集，不混成新成绩。
- 临时调试记录放本地；维护文档简短更新，不新增逐轮审批文件。本次用户明确要求的交接使用现有交接文件。
- 本次变更前的规范全文可通过 `git show fef61b8:AGENTS.md` 查阅。它是历史参考，不覆盖本页。
