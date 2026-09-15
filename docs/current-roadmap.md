# DeepChoice 当前实施路线

更新日期：2026-09-15

本文档是 DeepChoice 后续实施范围的当前事实源。`technical-design-engineering-enhancement.md`
保留完整设计空间和历史方案；若两者对“现在是否实现”存在冲突，以本文档为准。

## 1. 诊断

DeepChoice 已完成 Phase 0、Phase 1-A～1-G、Phase 2-A～2-C 和 Phase 6-A；Phase 2 的
运行接线、latest-run 摘要 API、预算闭环和 Streamlit 展示已通过测试与独立 Review。
重复成本、人工决策和确定性质量 smoke 等主要工程能力已经实现；Phase 3、Phase 4 和 Phase 5
也已完成，PR 5-2 已对默认 durable 路径做跨模块工程验收。项目尚未基于真实 case 建立当前版本
的重点指标基线，
更没有针对这些指标完成优化，因此当前阶段不能声称产品效果已最终验收或已经具备面试交付条件。

继续按原始企业级设计全面扩张，会提高维护和讲解成本，却未必改善研究结果或面试展示。
已完成能力保持不动；调整只作用于尚未实施的范围。

## 2. 指导原则

- 面向单用户、单实例、单 worker 的本地产品，不引入新的分布式基础设施。
- 每项新增能力必须至少改善一个结果：用户可见体验、报告可信度、成本可控性或可验证质量。
- 优先接通默认 durable 路径，不为旧兼容路径继续增加功能。
- 复用现有 Python、FastAPI、LangGraph、Streamlit 和成对 SQLite；不因抽象完整性引入新平台。
- Phase 5 已按两个 PR 收口；跨阶段工程验收和文档包含在 PR 5-2，没有另拆细碎 PR。
- 安全、预算和状态决策保持确定性；LLM 只负责研究内容，不负责执行这些规则。
- 已完成但未来不属于面试主线的能力不删除；展示取舍在完成真实指标优化后再决定。

## 3. 已完成基线

- Phase 0：请求/响应、错误、Retriever 契约和 `RunManifest`。
- Phase 1-A～1-G：SQLite 生命周期、恢复、fencing、事件/SSE、结果持久化和默认前端接入。
- Phase 2-A：`RunContext`、Trace/Budget 契约、策略冻结和 schema v8 骨架。
- Phase 2-B：默认 durable 运行节点与外部调用 Trace、latest-run 摘要 API 和 Streamlit 展示；
  已通过 Phase 级完整测试与独立 Review。
- Phase 2-C：原子预算门、append-only 结算、结构证据受限报告和预算摘要展示。
- Phase 6-A：安全 URL、输入 admission、集中脱敏和报告 HTML/PDF 安全。
- Phase 3：确定性引用验证及 durable retrieval cache/single-flight。
- Phase 4：单一 `evidence-insufficient` 决策门、前端交互和完整恢复验收。
- Phase 5：版本化核心资产、离线 smoke 和工程基础整体验收。

以上能力进入维护状态：只修复缺陷和默认路径回归，不继续横向扩展。

## 4. 当前实施范围

### Phase 2-B：最小可观测闭环（已完成）

目标：回答“一次报告经历了哪些节点和外部调用、哪里失败或重试、耗时多少”。

**PR 2-B1：运行接线**

状态：已实现并进入当前分支。

- 为默认 durable 工作流接入 node attempt 和 LLM/retriever external-call wrapper。
- 写入现有 `node_attempts`、`external_calls` 和必要的 `trace_events`。
- Trace 写入失败必须降级，不能改变任务状态、SSE 或报告结果。
- 只记录脱敏元数据、用量、状态与耗时，不记录 prompt、完整响应和报告正文。

**PR 2-B2：查询与展示**

- 已实现 `GET /api/v1/tasks/{task_id}/observability`，只读取产品 SQLite latest run，返回
  allowlisted 节点/调用与聚合；latest run 选择、run epoch/status 与 Trace 来自同一个 SQLite
  read snapshot。调用包含节点归属、run 内节点尝试序号和可选的数值 retry 序号；过期 started
  记录投影为 interrupted 或 unknown。旧 run policy、无 Trace 和无 latest run 均显式 unavailable。
- Streamlit 请求该 API，展示 durable 节点、调用、重试、失败和已知 token；API 不可用时回退
  现有 snapshot panels。
- API 聚合/白名单/历史/无 Trace、前端接入与回退的聚焦测试、Phase 级 full suite 和独立
  Review 均已通过。

完成标准已满足：默认运行可从 run 定位到 node/call；Trace 故障不影响任务正确性。

### Phase 2-C：标准预算闭环（已完成）

目标：让项目实际执行已冻结的标准预算，而不是只展示 token 统计。

**PR 2-C1：预留与结算**

状态：已实现并通过聚焦测试与独立 Review。

- 在现有 ledger 上实现原子 reservation/settlement，覆盖 LLM token、外部调用次数和 active time。
- 接入默认 LLM/retriever wrapper；重试、fallback 和 usage 缺失必须保留可解释状态。
- 未知价格保持 unknown，不按零成本处理；不建设动态计费或 provider 账单系统。

**PR 2-C2：触顶策略与校准**

状态：已实现；标准档采用用户提供的历史运行经验作保守初始校准，真实分布继续由后续运行
遥测验证，不声称已完成付费健康集的 95% 实测。

- 预算触顶且已有最低证据时生成受限报告；达不到最低证据时终止。
- 前端展示预算消耗、限制原因和结果是否受限。
- 标准档为 60,000 total token、96 次 LLM、72 次 retrieval、900 秒 active-time 和 80% 软提示；
  token/active 上限相对历史约 20,000 token/6 分钟分别保留约 3 倍/2.5 倍余量，离线 profile
  只验证结构 headroom，不伪造 provider telemetry。

完成标准已满足：任何新外呼都先过预算门；并发下不超发；触顶行为与用户已确认策略一致。

### Phase 3：引用可信与重复成本

目标：让报告中的关键引用状态可验证，同时减少同一运行中的明显重复检索。

**PR 3-1：确定性引用验证**

状态：已实现。新运行冻结 `research-v2`、state schema v2 和
`deterministic-citation-v1`；历史 v1 run 保持可读，但不做不兼容的同 run 恢复。

- 对报告关键引用执行可访问性、URL 规范和声明支持度的确定性检查。
- 状态仅使用 verified、unsupported、unreachable、unknown 等诚实结果。
- 报告和前端展示引用 warning；默认不增加第二轮 LLM judge。
- 动态 URL 复用安全 fetch，每个规范 URL 每轮最多请求一次，并在请求前预留 `http_calls`；
  临时网络与跨语言不确定性保持 unknown，运行结果不保存页面正文或原始异常。

**PR 3-2：轻量去重与缓存**

状态：已实现。durable Retriever 已在 Trace 与预算预留之前接入 cache；schema v9、关闭开关及兼容路径均有自动化测试覆盖。

- 只为 durable retrieval result 建立 SQLite v9 TTL cache，并使用每 run 的进程内 single-flight；默认启用，可通过 `RETRIEVAL_CACHE_ENABLED=0` 安全关闭。
- cache key 是规范化请求、source、immutable manifest identity 和 cache-policy version 的哈希，不持久化明文请求。
- 仅缓存通过 stable result contract 校验的成功结果；失败、非法或超尺寸结果不缓存。`/research` 兼容路径和无 `RunContext` 的调用绕过缓存。
- cache hit/coalesced waiter 不消耗 `retrieval_calls` 预算，也不生成 external-call Trace；只为真实外呼记录调用。保留 `retrieve()` 与 legacy `search()` 两个入口，不做 LLM response cache。
- leader 的失败、非法或超尺寸结果不会落盘，但同一 run 内已经等待该次调用的 follower 会复用该次结果，避免失败风暴；leader 被取消时 follower 才重新竞争。
- 写入后以有界批次惰性清理过期行；缓存数据库异常 fail-open，不改变检索成功/失败语义。

完成标准：关键引用有明确状态；同一运行的相同检索不会重复请求；缓存可安全关闭。

### Phase 4：单一 HITL 决策闭环

目标：只在证据不足且继续方向会显著影响结果时请求用户决策。

**PR 4-1：持久决策后端**

状态：已实现。产品 schema v10 新增 `hitl_decisions`；新运行冻结 `research-v3`、state schema
v3 和 `evidence-insufficient-v1`。唯一决策 gate 位于引用验证之后、报告生成之前，并仅用于
结构性证据不足且推荐方向实质不确定的 durable run。旧 `/research` 兼容路径保持绕过。

- 仅实现一个 evidence-insufficient gate，不实现原方案的四类 gate 矩阵。
- 支持“补充信息后继续、按现有证据生成受限报告、取消”。
- 决策与 task/run、已接受 checkpoint、state schema 与暂停 fencing epoch 绑定；相同提交幂等，
  不同 body 或过期/版本冲突不覆盖已提交结果。
- 决策 7 天过期；等待状态释放 lease、active deadline 与执行槽。重启后保留 pending 决策；
  合法 resolve 从绑定 checkpoint 恢复，过期则原子收敛为取消。
- durable API：`GET /api/v1/tasks/{task_id}/decision` 查询公开决策；
  `POST /api/v1/tasks/{task_id}/decisions/{decision_id}` 以 `If-Match` task version 提交。
  公开 projection/event 不含补充文本、checkpoint identity 或 fencing identity。

**PR 4-2：前端与恢复验收**

状态：已实现并完成恢复验收。

- Streamlit 在 durable SSE 收到 `waiting_for_input`/`decision.required` 后结束当前流并展示待决策原因、证据缺口、允许动作及 7 天有效期；等待期间不持续占用 SSE 连接。
- 用户提交后重新连接 durable SSE，并从最后收到的 `Last-Event-ID` 续接；若服务端要求 resync，先刷新 task/decision 快照，再续接事件流。
- 三个动作分别为补充信息继续、基于现有证据生成受限报告、取消。所有 resolve 请求携带当前 task version 的 `If-Match`；提交结果不确定时可用相同请求体安全重试，冲突时刷新状态，不自动改写用户选择。
- UI 只展示公开 decision projection。补充文本、checkpoint identity、execution epoch、lease owner、manifest 和内部 state 不得进入页面事件、日志或公开响应；报告正文继续遵循已有 HTML sanitizer 约束。
- 恢复验收使用独立的真实产品 SQLite 与 LangGraph checkpoint SQLite、真实 `StateGraph` 和 checkpoint saver；至少覆盖 pending decision 跨进程重启保留、相同 resolution 幂等、不同 body/过期版本冲突、七天过期收敛、取消不恢复图，以及合法补充信息从绑定 checkpoint 将同一 run 恢复且只执行一次。

PR 4-2 完成标准：pending 决策界面和 SSE 断开/续接行为符合上述契约；等待期间不占执行槽；真实双 SQLite/checkpoint 端到端验收证明重启后决策仍可处理，且一次合法 resume 只恢复一次正确 run。

### Phase 5：工程基础评估与收口

目标：证明 DeepChoice 的工程基础稳定、可恢复、可审计，并形成后续真实指标测量与优化可以
依赖的基线。本 Phase 不验收真实报告效果，也不制作面试交付材料。

**PR 5-1：最小版本资产与离线评估**

状态：已完成（2026-09-15）。

- 核心资产 registry 仅记录默认路径实际使用的 7 个核心 Prompt hash/version、`research-v3`、
  state schema v3、workflow nodes、citation/HITL policy 版本和三个报告模板版本；不保存
  Prompt 正文、密钥，也不扩建通用 Prompt registry。
- `smoke-v1` 固定为 12 个 fixture replay case：query analysis、引用验证、结论后处理、报告渲染
  各 3 个。评估全程不得调用 LLM/judge 或网络，只验证确定性代码路径、fixture 结构和报告结构。
- 评估 artifact 记录数据集 ID/version/hash/freeze date、评估时间、各项分母、当前 manifest ID、
  core asset registry ID，以及来源健康为 `not_run`/`degraded` 的明确状态。
- 该 smoke 集不代表真实模型语义质量，也不代表在线信源健康；不改变或混合历史 300-case
  benchmark 指标及其原有日期、数据集和分母。
- 本 PR 只包含版本资产与离线 smoke/eval。测试数量和工程一致性审计留给 PR 5-2；真实案例、
  重点指标优化和面试材料不属于当前 Phase 5。

PR 5-1 完成标准：资产 registry 可稳定复算；固定 12-case fixture replay 在无 LLM/网络下运行，
artifact 含可追溯版本和数据集元信息，并明确标记 source health 未执行；不能将 smoke 结果
描述为真实模型质量结论。命令与 baseline 检查说明见 [`phase5-offline-eval.md`](phase5-offline-eval.md)。

**PR 5-2：工程基础整体验收与收口**

状态：已完成（2026-09-15）。验收证据与遗留风险见
[`phase5-engineering-acceptance.md`](phase5-engineering-acceptance.md)。

- 跨模块复核默认 durable 路径，覆盖迁移、恢复、状态机、预算、Trace、引用验证、缓存、
  HITL、安全边界、SSE 和旧接口兼容约束。
- 审计测试数量增长，识别重复、低价值或只重复实现细节的测试；记录结论，不为减少数字而
  删除仍承担回归价值的用例。
- 审计默认路径中的死代码、旧接口/旧上游依赖、文档与实现偏差，只修复会影响工程基线或
  后续指标实验可信度的问题。
- 执行完整 CI、关键故障/恢复验收和独立 Review，形成简短的工程验收报告与遗留风险清单。
- 不运行付费 benchmark，不选取面试演示案例，不优化报告质量指标，也不制作架构讲解或
  面试材料。

完成标准：工程默认路径稳定且约束一致；测试与 CI 结果可复现；已知工程风险被记录；项目可以
安全进入真实 case 指标测量与针对性优化。此结论不得表述为产品效果最终验收或面试版本完成。

### Phase 5 之后的规划边界

当前实施范围在 PR 5-2 后结束。后续路线需要依据真实运行数据重新确认，建议顺序为：先冻结少量
代表性 case 与重点指标基线，再做针对性优化和回归验证，最后才整理可复现演示、架构讲解与面试
材料。上述工作不自动启动，也不属于 PR 5-2 的验收内容。

## 5. 不在当前实施范围

以下内容不再安排当前 Phase，也不作为当前稳定版门禁：

- 多用户认证、租户 ownership、RBAC/SSO、API key middleware 和 rate limiting。
- 多 worker、多实例、Redis/外部队列、PostgreSQL、Kubernetes 和分布式 Trace/OTel 平台。
- 通用计费平台、动态价格服务、provider 账单级对账和全量 LLM response cache。
- 四类 HITL gate、通用 Agent/plugin 平台和完整 Prompt 资产迁移。
- 所有静态 provider 的安全 fetch 迁移，以及浏览器矩阵、真实公网 TLS/SNI 等扩展安全验证。
- 大规模付费在线 benchmark；仅在明确需要且确认 API/费用时单独运行。

这些是明确的范围边界，不是当前路线中等待实施的阶段。

## 6. 实施顺序

`Phase 3 → Phase 4 → Phase 5（止于工程基础验收）`

Phase 6-A 已完成并维持，不再单独安排 Phase 6-B。完成 Phase 5 后，根据真实 case 与重点指标
重新规划优化阶段；在优化结果稳定前，不进入面试交付，也不自动恢复本文件列出的范围外事项。
