# DeepChoice 下一会话交接摘要：产品效果优化

更新日期：2026-09-15

用途：将本文作为新 Codex 对话的第一条上下文。它只交接已经验证的仓库事实、用户决策和下一阶段
边界，不代替仓库中的 `AGENTS.md`、当前代码或测试。

## 1. 当前结论

DeepChoice 当前授权的工程基础路线已经完成。Phase 5-2 对默认 durable 路径做了跨模块验收，
最终结果为 **1040 passed、0 skipped**；离线 fixture-replay smoke 为 12/12，静态检查、依赖检查
和 Compose 配置检查通过，独立 Review 没有遗留可操作问题。

当前分支为 `codex/phase5-engineering-acceptance`，Phase 5-2 提交为
`0a2ad10 fix: close phase 5 engineering foundation`。该提交尚未在本摘要中声称已推送或合并。

Phase 5-2 开始时有 1022 个收集项，本轮针对六项实际缺口增加 15 个 `test_*` 函数、参数化后
增加 18 个收集项。历史上最大的增长来自 331 项生命周期状态矩阵参数化，并非 331 个重复手写
测试；验收没有为了压低数量删除有分层回归价值的测试。

这只代表工程基础验收通过，不代表真实研究效果已经优化，也不代表面试交付已经完成。详细证据和
遗留风险见 `docs/phase5-engineering-acceptance.md`。

## 2. 已完成的能力

- Phase 0：Pydantic 请求/响应/错误契约、`RunManifest`、Retriever 稳定接口。
- Phase 1：SQLite migration、Repository/CAS、durable task/run、lease/fencing、恢复、SSE、结果
  持久化、旧 snapshot/API 兼容和 Streamlit 默认路径接入。
- Phase 2：RunContext、Trace、原子预算 reservation/settlement、预算触顶后的确定性受限报告门、
  observability API/UI。
- Phase 3：确定性引用验证、durable retrieval cache、TTL 和 single-flight。
- Phase 4：单一 `evidence-insufficient` 决策门、三个动作、七天过期、前端交互和重启恢复。
- Phase 5：版本化核心资产、12-case 离线 smoke、工程基础整体验收。
- Phase 6-A：动态 URL/DNS/redirect 安全、输入限制、日志脱敏、服务端报告 HTML/PDF 清洗。

本轮验收还修复了预算并发锁存、等待决策时 SSE 服务端收流、Tavily 出站旁路、Python/Docker
版本漂移、Tavily key 状态持久化和旧接口弃用头覆盖。

## 3. 产品定位与用户决策

DeepChoice 是用于应届生面试展示的个人项目。下一阶段的核心不是继续堆企业级基础设施，而是用
可复现的真实 case 证明：报告更正确、证据更可靠、耗时和 token 可解释，并且项目作者能够讲清楚
取舍与改进过程。

已经实现的工程能力不需要为了“简化”而删除，但以下范围不进入当前优化路线：多用户认证/RBAC、
rate limiting、分布式 worker、外部队列、PostgreSQL/Redis/OTel 平台、通用计费和多决策门 HITL。

与预算有关的既定事实：

- 工程改造前，项目通常约 6 分钟、最多约 20,000 token 生成一份报告；这是用户提供的历史经验，
  不是当前版本重新测量的 benchmark。
- 当前 durable 标准硬限制冻结为 60,000 total tokens、96 次 LLM、72 次 retrieval、900 秒 active
  time，80% 时软提醒。它是安全上限，不是优化目标。
- 暂不凭感觉收紧预算。应在工程基础完成后先跑当前版本真实 case，再依据数据调整。
- 预算触顶后，满足最低结构证据门则生成显式受限报告；否则以
  `BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE` 终止。
- HITL decision 的过期时间为七天。

## 4. 下一阶段：产品效果优化

下一阶段应先建立当前版本基线，再做针对性优化。不要直接沿用旧 benchmark 数字，也不要先改
Prompt、模型或预算再补测量。

建议按以下顺序推进：

1. 选取少量但有代表性的真实 case，覆盖不同技术决策难度、资料充分度、冲突程度和中文/英文来源。
2. 冻结 case、运行环境、模型/Prompt/工作流版本和评价口径，形成可复现的当前基线。
3. 同时观察报告正确性、引用支持度、来源质量、冲突处理、完成率、耗时、token 和外部调用数；
   不用单一分数掩盖失败原因。
4. 对失败 case 做错误分类，只选择影响最大的 1～2 个瓶颈进入首轮优化。
5. 每项优化保留 before/after 结果和回归测试；确认效果后再讨论预算档位、演示 case 和面试材料。

拆分应保持适中：每个优化 Phase 最多两个实现 PR。第一个 PR 建议只负责“真实 case 与基线协议”，
第二个 PR 再针对首要瓶颈做一轮可测量优化。不要把指标设计、多个算法改动、UI 展示和面试材料塞进
同一个 PR。

## 5. 下一会话开始时应做什么

1. 先运行 `git status --short --branch`，确认分支和用户改动。
2. 阅读 `AGENTS.md`、`docs/current-roadmap.md`、`docs/phase5-engineering-acceptance.md` 和
   `docs/phase5-offline-eval.md`，以当前代码和测试为事实源。
3. 先给出产品效果优化阶段的适中 PR 拆分、case 选择原则和指标定义，等待范围确定后再运行真实
   benchmark 或修改生产逻辑。
4. benchmark 会调用付费/外部服务；只有用户明确要求、环境变量齐备且 health check 通过后，才
   能运行批量 case。不得打印 `.env` 或 API key。
5. 不得混用 2026-08-31 的 300-case 历史 benchmark 与后续小规模 Qwen adaptation 指标；任何
   数字都必须附 case 集、日期和分母。

如果使用子 agent，保持职责清楚：`code_explorer` 只读定位；`complex_implementer` 处理跨模块、
并发或高风险修改；`focused_implementer` 处理边界清楚的一般代码；`independent_reviewer` 做最终
只读复审。所有实现仍需由主 agent 整合、跑完整验证并提交。

## 6. 已知但不阻塞当前优化的边界

- 本地尚未实际执行 Python 3.11 CI；CI 定义已经覆盖 3.11/3.12。
- 未运行当前版本的真实网络、LLM 或付费 benchmark，因此没有新的产品效果结论。
- TLS/SNI、压缩响应解压限额、浏览器级 XSS 尚无真实端到端验证。
- SSE keepalive 和事件 retention 留待真实反向代理/生产部署前处理。
- durable API 仍是单用户可信网络模型，SQLite runtime 仍限定单实例、单 worker。

## 7. 可直接粘贴到新对话的开场指令

```text
当前项目是 D:\deepchoice-agent。工程基础路线已经完成，Phase 5-2 验收提交为 0a2ad10，完整
测试为 1040 passed、0 skipped。请先阅读根目录 AGENTS.md、docs/current-roadmap.md、
docs/phase5-engineering-acceptance.md、docs/phase5-offline-eval.md 和本交接摘要。

下一阶段进入产品效果优化。项目定位是应届生面试用个人项目：保留已实现能力，但不继续扩张企业级
基础设施。请先基于当前代码，把产品效果优化拆成适中粒度的小 PR，并优先设计少量代表性真实 case、
当前基线和评价指标；不要先修改预算、Prompt 或模型，也不要未经确认运行付费 benchmark。指标必须
同时覆盖报告正确性、引用支持、来源质量、冲突处理、完成率、耗时和 token，并附 case 集、日期和
分母。实现时区分复杂实现 agent、一般实现 agent 和独立 Review agent 的职责。
```
