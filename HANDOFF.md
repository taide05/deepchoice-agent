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

## 最新真实结果（2026-10-26，200 例正式批跑）

- 代码冻结点 `66df664`；题集 `.scratch/cases/cases_formal_200.json`（50 候选对 × 4 场景 =
  200 例，12 类别，无 expected_winner 标注；SHA-256 `46728f20…`）；并发 5、失败不补跑。
- **200/200 完成**（0 失败），批跑 13:22–15:22；单例 wall p50 169.3 s / p95 266.8 s；
  已知 LLM tokens 10,618,062；报告 p50 19,331 字符、全部含引用与“尚未可知”段。
- 决策状态：conditional 157、recommended 12、insufficient 26、invalid 5；置信度 low 156 / medium 44。
- 分层抽检 30 例（种子 20261026）：可用 30/30、decision-grade 18/30、关键错误 0、
  轻微过度拒绝 1/30；31 个非决策案例中 5 个 invalid 实际含可执行分支建议（状态误标）。
- 已披露缺陷：**arXiv 噪声**（90/200 报告引用 arXiv，66/200 引用 ≥10 条；夜间已修，见下）、
  5 例状态误标、45/200 例官方正文 0 页；初版报告的“2 例内部检索式泄漏/12 条无关导航链接”经更严格
  复检为启发式误报，真实数量均为 0；并发批跑下 Tavily 调用数不可归因。
- 正式报告：`.scratch/cases/runs/formal-200-review/FORMAL_200_REPORT.md`；逐例产物在
  `.scratch/cases/runs/formal-200-20261026/`。该结果是“完成率 + 抽样内容评审”，**不是标准答案准确率**。

## 2026-10-26 夜间修复（只代码/单测/离线，无新增付费运行）

- **D1 决策状态契约**（提交 `bd9defe`）：conditional 答案的 `ranked_options` 结构坏或带版本后缀时，
  若推荐文本有明确分支并点名 ≥2 个声明候选，则用声明候选重建 options、保持 conditional；不猜 winner；
  5 个 invalid 中 4 个可恢复，F200-074 因文本只提一个候选保持 invalid。8 个新单测。
- **D2 arXiv 噪声**（提交 `4ab2b85`）：非 ML/学术题不再查 arXiv（空来源、不发请求）；学术题只保留
  命中候选的结果。离线重放 200 例：177 例将跳过 arXiv，预计移除约 96.7% 已保存 arXiv 引用。
- **D3 展示缺陷更正**：更严格复检 200 份报告：内部检索式泄漏 0、无关导航 0；此前 2 例/12 条是
  启发式误报，`analyze_batch.py` 指标定义已更正，旧指标另存 `metrics_crude_heuristic.json`。
- **D4 官方覆盖（部分）**：45 个 0 页案例中映射缺口为 0，主因是发现条目（prior search/mapping/derived）
  超过 4 页预算——**不是自评重试**（自评节点是图终点，不重跑图，`retry_count=1` 只是复核标记）；
  批跑服务 8/24→12/32 后 F200-065 恢复正文，SPA/短正文（F200-144 类）仍需专门回退，未做。
- **D5 并发计数（部分）**：批跑服务记录进程级总用量（`batch_usage_total.json`）；逐例隔离未做。
- **金标评估（Z1–Z3，0 API）**：30 例分层抽样冻结（SHA-256 `309b395f…`，种子 `261026`），
  答案键 14 决定性 + 16 条件式；用已保存 200 份报告算修复前基线：**可接受/条件命中 24/30（80%）**，
  决定性方向 14/14、条件翻转 10/16、严格 Top-1 2/14（辅助口径）。产物在 `.scratch/cases/gold/`。
- **下一轮见下面的 round1/round2 记录**；通过后再谈最终 200；交付材料在小样本验证后写。

### 第一轮小样本验证（2026-10-26 夜，9 例，用户已批准）

- 9/9 完成、0 失败；实际 **484,102 known tokens**（同 9 例基线 449,429，+7.7%）、
  进程级 91 LLM 请求/85 Tavily POST、0 rejected；约 9 分钟。
- D1：4 个 invalid → 3 conditional + 1 recommended；但 `decision_validation_recovered` 未触发，
  说明这次是新模型输出合法结构，**恢复代码路径未被真实触发**（仍只有单测覆盖）。
- D2：非学术案例 arXiv 引用 113→3（移除 97.3%）；ML 对照 F200-144 22→3（保留候选相关论文）。
- D4（批跑 8/24）：官方正文“至少 1 页”案例 **4/9→7/9**；F200-065 仍 0（timeout+预算耗尽）、
  F200-144 仍 0（short_prose_only）；总页数 9→12。
- D3 无需重跑，复检为误报更正；D5 不在本轮范围。
- 结论：**不是全部缺陷修复完成**；D1/D2 方向验证、D4 部分改善。详情见
  `.scratch/cases/runs/validation-r1-20261026/VALIDATION_R1_FINDINGS.md`。

### 第二轮小样本验证（2026-10-26 夜，9 例：7 holdout + 065/144 重测，用户已批准）

- 9/9 完成、0 失败；**461,488 known tokens**、64 LLM/69 Tavily；批跑官方预算 12/32；约 9 分钟。
  两轮累计 **945,590 tokens、155 LLM、154 Tavily**（在批准范围内）。
- D1 恢复路径**真实触发成功**：F200-065 invalid→conditional，恢复 options 为 `["MySQL","MariaDB"]`；
  round1 的“机制未验证”缺口补上。
- D2 holdout 泛化通过：7 例未见案例 arXiv 引用 29→0、7/7 完成；ML 重测 144 22→0（过滤可能偏严，
  但报告仍有 6 个来源、内容未见空洞）。
- D4：12/32 修复了 F200-065 的预算问题（官方正文 0→2）；F200-144 仍 0 页——是
  `not_prose:short_prose_only`（GitHub Pages/SPA），不是预算，SPA 回退未做。9 例“≥1 页”覆盖 6/9→8/9。
- 监控项：部分报告变短（035/065/144 字符 -26%/-28%/-32%）、部分变长（082/160 +20%/+23%）；
  抽查 035/144 内容仍完整，但是否影响可用性需内容复核（建议 2–3 份，不跑 API）。
- 详情：`.scratch/cases/runs/validation-r2-20261026/VALIDATION_R2_FINDINGS.md`。

### 零 API 工作（2026-10-27 夜，用户已批准）

- **16 份验证报告全量 C1–C4 复核**（不是抽样）：usable **16/16**、decision-grade **14/16**、
  C4 关键错误 **0**、过度拒绝 0；两份 C2 不足（139 缺 W&B 官方正文、144 的“AutoGen 维护模式”
  仅来自竞品博客）。结构缺陷：F200-065 What 段为空（待渲染层修复）。表在
  `.scratch/cases/runs/validation-review/CONTENT_REVIEW.md`。
- **变薄根因**：字符变化是模型写作方差 > 检索源组合 > 自评修正数 > arXiv 移除的混合结果，
  不推荐为长度改代码；唯一确定的结构问题是空 What 段。详见 `THINNESS_ROOT_CAUSE.md`。
- **自评成本效率**：自评占 **49.2% tokens（5.23M；26.1k/例）**，111/200 零修正；不是重试。
  四个方向的离线评估与 A/B 计划见 `SELF_REVIEW_COST_ANALYSIS.md`；已加 opt-in 开关
  `SELF_REVIEW_MODE` / `SELF_REVIEW_EVIDENCE_BUDGET_CHARS`（默认行为不变，提交 `18e4f12`）。
- **SPA/llms.txt 回退**：同源 `llms.txt`/`llms-full.txt` 回退已实现并有测试；GitHub Pages 的
  raw README 会被官方身份策略拒绝，不放松身份；F200-144 类仍可能 0 页（已知限制）。
- **arXiv 过滤放宽**：候选簇主题提示 + 分析类词；已保存 20 个 AI/ML 案例 137 条结果中，
  严格 26 条 → 放宽 47 条；需谷价实测 2–3 例确认噪声/收益。
- 零 API 汇总：`.scratch/cases/runs/validation-review/ZERO_API_SUMMARY_20261027.md`。
- **新运行规则（立即生效）**：任何付费研究运行（无论题集大小）**只在谷价时段**，且必须先报批；
  开发/单测/离线分析/内容复核不受限。最终 200 例仍未决定。

### 谷价 A/B 实验（2026-10-27 12–14 窗口，用户已批准）

- 18 次 A/B 运行（6 例 × 默认/自评预算12k/输出约束）+ 3 例 SPA/arXiv 实测 + 18 次受控
  review-only 重放；合计约 **1,350,777 tokens**（在批准范围内）。
- 三臂总 tokens：A 287,416 / B 284,895 / C 247,300；自评 tokens：A 155,457 / B 137,618 /
  C 112,713。**输出约束**省最多（总 −14%、自评 −27.5%）。
- 受控重放（同一输入）：default 137,630 tokens / 修正 4；budget12k 134,033（−2.6%）/ 修正 2；
  output constraint 110,893（−19.4%，completion −43.8%）/ 修正 1。
- **关键发现：模型输出非确定性**。在 evidence_visible<12k（prompt 完全相同）的案例上，default 与
  budget12k 仍产出不同修正（如 F200-130 2 vs 1、F200-159 2 vs 0），说明 temperature=0 下 API
  仍有运行间方差；单次 A/B 的修正差异不能归因配置。因此不能凭本轮默认启用输出约束或预算。
- SPA/arXiv：GitHub Pages（F200-144）同源 llms.txt 回退被执行但 404，官方正文仍 0；
  F200-119 非学术 gate 正常（0 条 arXiv 源）；F200-148/144 的 arXiv 请求 **ReadTimeout**，
  **放宽规则未被实际测试**。
- 结论：输出约束是唯一明确的省钱候选，但需重复受控实验确认修正质量；evidence budget 12k 收益太小，
  trigger 不启动；SPA/GitHub Pages 保持已知限制；arXiv 放宽需换窗口重测。
- 详情：`.scratch/cases/runs/ab-analysis-20261027/AB_EXPERIMENT_FINDINGS.md`、
  `.../REPLAY_RESULTS.json`。

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

工程链已能批量运行并在小样本上验证修复：200 例基线 200/200 完成；round1/2 共 18 次运行完成、
D1 恢复路径真实触发、D2 arXiv 在 holdout 上 29→0、D4 预算修复使 F200-065 恢复正文。
16 份验证报告全量复核 usable 16/16、decision-grade 14/16、关键错误 0。但**还不是“可投递”状态**：

- 自评成本效率是新发现的问题（49.2% tokens、111/200 零修正、completion 占 41%）；
  谷价 A/B 显示输出约束可省约 14–19% tokens，但模型非确定性使修正质量结论待重复实验；
- arXiv 过滤放宽只有离线/单测证据，谷价实测遇到 arXiv API ReadTimeout，尚未验证；
- SPA/静态回退已实现并实测：GitHub Pages 受身份策略限制仍 0 页，属已知限制；
- C2 一手性仍是内容质量短板（139/144 两例不满足 decision-grade）；
- 官方正文覆盖未达标（45/200 为 0 页；GitHub Pages 受身份策略限制）；
- F200-065 空 What 段等结构缺陷待修；
- 最终版全量指标（200 或用户同意的分母）尚未产出，交付材料不能先写数字。

来自本批与真实运行材料的主要差距：

- arXiv/低相关来源进入报告（已大改，放宽策略待实测）。
- 决策状态与内容不一致（D1 已修，真实触发验证通过）。
- 官方/版本化证据覆盖不足（预算问题已定位；SPA/GitHub Pages 仍受限）。
- 来源归属与“页面在讲哪个候选”的对应仍可能出错。
- 自评高成本、命中率中等，需要在谷价 A/B 后再决定组合。
- 报告长度是混合方差，不是单一 bug；需内容复核而不是加字数。

## 下一步（用户已确认的方向）

1. **重新设计运行/评测案例**：按项目真实输入方式写简短问题 + 必要场景与约束，让澄清、
   查询分析和检索能消化；不使用 Codex 过度细节化的案例作为新验收，旧案例只作开发回归。
2. **先跑出一份可展示报告**：记录版本、实际用量和真实输出；按“是否回答原问题、依据是否
   适用、条件与缺口是否明确”评审，定位问题出在哪一层，做最小修改。
3. 现阶段不做“可用率/阈值/成本对照”：真实运行的唯一目的是拿到真实报告、数据和报错来定位
   修复；用量如实记录即可。需要决定是否删减复杂环节时，再考虑对照。
4. 现有 9 节点阶段划分不简化；问题与修复以真实报告内容为准，不回到工程向的检查堆叠。
5. 现阶段内容评审全部由 dsh 完成；投递材料不写评审方式标注。

## 当前阶段计划（截至 2026-10-28）

- 10/26：已完成 F5（子问题固定 5 条）与 F4（官方深层文档发现、78 个技术名映射、官方根页正文准入）
  修复；12 题测试集 12/12 完成且结构达标；起草并冻结 200 题正式题集，夜间完成 200/200 正式批跑。
- 10/26 夜：D1/D2 修复（提交 `bd9defe`/`4ab2b85`）；round1/2 共 18 次小样本验证完成；
  两轮累计 945,590 tokens、155 LLM、154 Tavily。
- 10/27 夜（零 API）：16 份验证报告全量复核；变薄根因；自评成本分析与 opt-in 开关；
  SPA 同源 llms 回退；arXiv 分组放宽（提交 `18e4f12`）。
- 下一步（需用户批准、谷价时段）：
  1. **重复受控重放（最优先）**：6 例 × 2 配置（default vs output constraint）× 3 次重复
     = 36 次 review-only，约 0.7M tokens；用均值/方差判断修正质量是否下降；
  2. **ML arXiv 重测**：F200-144/148 等 2 例（上一轮 ReadTimeout），约 0.1M tokens；
  3. 若重复实验通过，再决定是否默认启用输出约束；evidence budget 12k 暂不做；
  4. 全部通过后再决定最终 200 例（未决定）；交付材料在其后。
- 不设固定轮数；某批修复没有可观察改善时停下来重谈方法（允许整段简化）。
- 以上为开发计划，不是成绩承诺；正式指标口径与限制见 `FORMAL_200_REPORT.md`。

## 保留材料与边界

- 保留：`outputs/` 历次运行、`.scratch/v*_seal`、根目录 `run_record*`/`run_payload*`、
  `D:\deepchoice-dsh` 的 v9–v12 材料与 `r10_diag2`、`D:\deepchoice-agent\.scratch\r10_round2`、
  `7da3701`/`ae5f3f3` 提交、2 个 stash。均不自动移植、不删除。
- 不做：接入 durable `/api/v1/tasks`、移植 durable 线代码、修复其测试、reset 回 `48b32bd`、
  push/发布/历史重写。
- 真实费用与用量照实记录；unknown 不写成 verified，不伪造支持。

## 评估与投递口径（用户已确认）

- **唯一投递验收是正式指标**：固定题集/样本、分母、日期、基线、评审口径都要写清。2026-10-26
  已产出第一份 200 例正式批跑（完成率 100%、抽检 usable 30/30、decision-grade 18/30），但报告
  已披露 arXiv 噪声、状态误标与官方覆盖缺陷，**尚不足以宣称达到投递标准**；是否在修复后重跑
  升级指标由用户决定。不得把该批数字写成标准答案准确率。
- “报告可展示”“单例内容可用”“相关测试通过”只是开发过程中的临时信号，用于判断是否继续投入；
  不是成绩，不进入投递材料，也不与正式指标混用。
- 报告有用性按内容判断：是否帮助理解倾向、理由、以及会改变选择的条件；区分“会让建议失效的
  遗漏”和“可以以后再补的细节”；允许有条件建议，不接受只有“证据不足”的空报告。
- 防止过度拒绝：确实错误、依据不足、自动核验失败、结构不合规分别记录，不自动统一删除；已有
  依据的分析不因核验形式失败被整体丢弃。
- 现阶段不做对照/成本比较门槛：当前目的是多跑真实报告、收集数据和报错用于修复；用量照实
  记录。以后需要决定是否删减复杂环节时，再做同案例简单基线对照。
- 现阶段内容评审全部由 dsh 完成；投递材料只写报告实际内容和实测数据，不写评审方式标注。
- 节奏：普通失败继续调整；连续真实运行没有可见改善时回来重谈方法，不自动续投。投递材料与
  开发并行准备，只写能解释、能复现或能出示依据的内容。

## 文档

活动文档：本页、`AGENTS.md`、`README.md`。历史记录：`CHANGELOG.md`、`RETRACTIONS.md`、
`fix_pack_*.md`、`run_record*.md`、`template-data/`、`template-outputs/`、
`local_cleanup_archive/`、`.scratch/`。
