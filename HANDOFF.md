# DeepChoice 恢复线：当前状态与接续

更新：2026-10-26。给接手开发的 dsh 看代码身份、真实结果、材料位置与下一步。
历史过程在 Git、`CHANGELOG.md`、`RETRACTIONS.md` 和本地 run 记录里，不在此重复。

## 代码身份

| 项 | 值 |
|---|---|
| 工作区 | `D:\deepchoice-precodex` |
| 分支 | `precodex/deepseek-adapter` |
| HEAD | 本交接文档提交 |
| 生产代码基点 | **`b080213`**（恢复线代码；其上仅文档提交） |
| 历史恢复起点 | `48b32bd`（只追溯，不 reset） |
| 入口 | `POST /research` + `frontend/app.py`（Streamlit） |
| 解释器 | `D:\deepchoice-agent\.venv\Scripts\python.exe`（3.12.4）+ 显式本树 PYTHONPATH |
| 用户修改/未跟踪 | `learned_docs.json` 修改与 17 项既有运行材料保留原位 |

## 能力现状

- 6 路检索（Tavily 网页、官方文档、GitHub、ArXiv、社区、本地知识库），统一来源/失败语义，
  Tavily 多 key 轮换与耗尽池；官方正文经统一安全抓取（大小、期限、重定向、编码有界）。
- 来源 4 维规则评分、冲突检测 + 两阶段仲裁、证据链组装、结论综合、6 项自审与定向重试。
- 3 种报告格式（what_why_how / evidence_first / comparison_matrix），引用编号与目录，
  Markdown/PDF 导出；Streamlit 前端含澄清、进度、观测面板和报告阅读。
- 配对诊断入口 `scripts/launch_pair.py` / `pair_worker.py` / `run_pair.py`（同一共享采集，
  基线臂 vs 候选臂）；`scripts/seal_case.py` 冻结案例；`run_service.py` 启动受守卫的单次运行。
- 模型：DeepSeek Flash（默认 `deepseek-v4-flash`）；旧 Qwen/DashScope 名称只是兼容，不再使用。

## 最近的真实结果（2026-10-22，v12 配对）

- 任务 `v12pair-f3166ac23bcc`（Temporal vs Camunda），candidate commit `f151361`。
- **两臂均未通过冻结正式门槛**：baseline `needs_review`（5 项必需内容全 partial）；
  candidate 仅诊断带 `usable (conditional, lower band)`，5 项同样 partial、0 个 score-3，
  未过正式 C1“版本化官方证据”。
- 实际用量：共享采集 1 次；总计 7 LLM、6 Tavily POST、官方 HTTP 5（4 次页面尝试、3 个全文页、
  1×403）；baseline 23,535 tokens/70 s，candidate 59,861 tokens/153 s；合计 known
  85,916 tokens、263.8 s，cost unknown；未补跑。seal 在 `.scratch/v12_seal`，报告在
  `outputs/v12pair-f3166ac23bcc/` 与 `D:\deepchoice-dsh\v12_run/`。
- v12 之后代码还有两个修复：`e0e4aa1`（决策状态与自审撤回统一）、`b080213`（撤回引用同步、
  候选校验），**尚无新的真实运行验证**。历史 668 项测试通过是旧记录，本次未重跑。

## 当前判断

工程链能运行、能出报告、能展示与导出；内容质量还没达到“可展示的正式报告”。

来自真实运行材料的主要差距：

- 官方/版本化证据覆盖不足（决定性命中页少，snippet 多，部分官方页抓取失败）。
- 来源归属与“页面在讲哪个候选”的对应仍可能出错。
- 报告对问题的承诺可能大于实际内容（例如条件推荐只剩资料描述）。
- 生成的结论/数值可能超出已保存证据的适用范围。

## 下一步（用户已确认的方向）

1. **重新设计运行/评测案例**：按项目真实输入方式写简短问题 + 必要场景与约束，让澄清、
   查询分析和检索能消化；不使用 Codex 过度细节化的案例作为新验收，旧案例只作开发回归。
2. **先跑出一份可展示报告**：记录版本、实际用量和真实输出；按“是否回答原问题、依据是否
   适用、条件与缺口是否明确”评审，定位问题出在哪一层，做最小修改。
3. 报告可用后再做链路稳定性与小样本真实指标；正式指标另定样本、日期、分母与限制后发布。
4. 现有 9 节点阶段划分不简化；问题与修复以真实报告内容为准，不回到工程向的检查堆叠。

## 保留材料与边界

- 保留：`outputs/` 历次运行、`.scratch/v*_seal`、根目录 `run_record*`/`run_payload*`、
  `D:\deepchoice-dsh` 的 v9–v12 材料与 `r10_diag2`、`D:\deepchoice-agent\.scratch\r10_round2`、
  `7da3701`/`ae5f3f3` 提交、2 个 stash。均不自动移植、不删除。
- 不做：接入 durable `/api/v1/tasks`、移植 durable 线代码、修复其测试、reset 回 `48b32bd`、
  push/发布/历史重写。
- 真实费用与用量照实记录；unknown 不写成 verified，不伪造支持。

## 评估与投递口径（用户已确认）

- **唯一投递验收是正式指标**：固定题集/样本、分母、日期、基线、评审口径都要写清。当前版本
  还没有这样的正式指标，因此**不得声称已达到投递标准**。
- “报告可展示”“单例内容可用”“相关测试通过”只是开发过程中的临时信号，用于判断是否继续投入；
  不是成绩，不进入投递材料，也不与正式指标混用。
- 报告有用性按内容判断：是否帮助理解倾向、理由、以及会改变选择的条件；区分“会让建议失效的
  遗漏”和“可以以后再补的细节”；允许有条件建议，不接受只有“证据不足”的空报告。
- 防止过度拒绝：确实错误、依据不足、自动核验失败、结构不合规分别记录，不自动统一删除；已有
  依据的分析不因核验形式失败被整体丢弃。
- 对照方式：同一案例、同一共享证据，比较当前完整链与简单基线的回答质量和成本；若某个复杂环节
  没有带来可见回答收益，提出来讨论删改，而不是默认保留。
- 节奏：普通失败继续调整；连续真实运行没有可见改善时回来重谈方法，不自动续投。投递材料与
  开发并行准备，只写能解释、能复现或能出示依据的内容。

## 文档

活动文档：本页、`AGENTS.md`、`README.md`。历史记录：`CHANGELOG.md`、`RETRACTIONS.md`、
`fix_pack_*.md`、`run_record*.md`、`template-data/`、`template-outputs/`、
`local_cleanup_archive/`、`.scratch/`。
