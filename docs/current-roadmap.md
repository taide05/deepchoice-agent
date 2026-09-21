# DeepChoice 当前实施路线

更新日期：2026-09-21

O1 剩余交付按用户要求组织为 3 个 PR：单例资格与候选冻结 → 正式 48-run 串并发配对
及逐轮评审 → 评估结项与一个优化假设。原 A/B、C1/C2 离线完成状态保留；协议 v4
阈值/预算不变。2026-09-21 的原有界持续授权覆盖候选 `15ca251` 的一次 P01 资格、资格通过后
两轮各 12 serial + 12 concurrent，以及本地 O1-PR3 收口；用户随后把总研究 run 上限由 49
调整为 59，以容纳停止前已计入的 11 个 run 和仍需 fresh 执行的 48 个正式 run。
范围与依赖以 [O1 PR 划分](o1-next-steps.md)为准。

2026-09-18 用户授权实施 O1-PR1：先完成单轮限额前置、相同候选环境冻结、真实研究内
冷加载与等待 HITL 即停的采集入口，离线验收及独立复审后执行一轮前置和 P01 一次。
失败停止、不循环探测、补跑或恢复；准备费用单列，研究硬预算不变。
该次授权和结果现为历史事实；实时结果及候选是否取得资格以
[单例验真](o1c-single-case-verification.md)为准。

最新 PR1 状态：**候选 `15ca251` 的助手暂定单例测量资格通过**。2026-09-21，
product-baseline-v1/1.0.0，P01 × 1 completed（108.282 秒 / 11,914 token）；68 原子台账、
独立复核、产品库/immutable result 核对及候选冻结闭环。资格使用持续授权的 1/49，正式
两轮剩余 48；来源缺证、动态 pinned CONNECT/TLS、人类校准、硬件稳定和正式串并发门禁
仍未完成。PR2B 控制链已重绑定该候选；O2 及 push/merge/release/发布未授权。

最新 PR2B 状态：source-aware 控制提交 `91d56cd` 使用 fresh 根执行 `15ca251`。serial-r1
完成 12/12，形成 12 份报告（1 份 limited），146,801 tokens、179 LLM / 72 retrieval、0 failed。
concurrent-r1 一次准入并观测 12 路 running，但 12 个 durable API 轮询在约 105～107 秒全部
`ReadTimeout`，控制器按 `PR2_CASE_OR_BUDGET_STOP` 停线；0 并发报告，11 cancelled、
P04 interrupted，service graceful exit 0。停线前 97 个 health 样本均 200、authority 有效，
heartbeat/lease loss 为 0、最低可用内存 1.292 GiB；没有先发 provider 异常，内部响应中断
原因仍未确认。累计使用 35/59、剩余 24；该根不得重启、补跑或拼接，第一轮门禁、第二轮及
O1-PR3 均未启动。进一步生产修复、重新资格和增加完整 fresh 配对额度需另行批准。

2026-09-18 的旧候选 `7d622fd` 资格及其后续正式尝试保留为历史证据，不能与新候选拼接。
更早的继续实施断点：独立新前置五源 5/5、JSON/tool 通过，但控制器启动前
可用内存不足 2 GiB，尚未启动服务或提交 P01，44/48 不变；已定位并最小修正嵌入依赖
提前导入。该状态已由后续资格和持续授权取代，旧证据不移贴。

此前 PR1 断点：入口离线验收及独立复审通过，但 2026-09-18 03:45 UTC 前置仍 4/5，
arxiv local-proxy 投影 rate_limited，6 次保守 HTTP 后停止，付费 Tavily/LLM/新研究均 0。
P01 未提交，44/48 不变；单例资格 unavailable，PR1 未完成、未形成 PR2 锁定候选。
原件/输入身份与未覆盖项见单例验真；不自动重查、补跑或进入 PR2。

前次 O1-C 断点：C2 可信本地 CONNECT 离线验收完成；随后获批 C3 一轮前置及 P01 一次，
但 2026-09-18 网络健康 4/5、arxiv gate rate_limited 后即停。Tavily 付费/LLM/研究均未执行，
累计 44/48 不变；后续真实调用另确认，不自动重查、补跑或进入 D/E/O2。
依据与计数审计见 [单例验真](o1c-single-case-verification.md)。
随后获批的同路由 arxiv 单探测 HTTP 200、当前无 gate 冷却；旧限流细因未确定，
完整前置和 P01 未执行，44/48 不变，不与旧四源拼表；见 [阻断诊断](o1c-blocker-diagnosis.md)。

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

2026-09-16 已按用户要求检查并处理影响基线的旧工具/说明，清单和正式实测前的剩余门槛见
[基线准备检查](baseline-readiness-audit.md)。默认路径保持 durable；旧直连 benchmark 单独隔离。

产品效果优化的下一阶段方案见
[`product-effectiveness-optimization.md`](product-effectiveness-optimization.md)，其中定义案例、
指标、运行协议和两个优化 PR 的交付顺序。2026-09-16 用户已明确要求先完成全部 LLM 的
DeepSeek Flash 适配，作为新基线的前置变更；该适配不代表已证明效果改善。真实案例冻结与
付费实测仍按协议执行；O1 使用固定 12 例对照整任务 serial=1 与 concurrent=12，并各重复两次；
这 48 个 run 只用于基线和冻结候选验收，不要求每次代码编辑都跑付费批次。

48-run 额度及官方参考清单/案例冻结已在本会话获用户确认；最小 LLM 兼容探测、完整检索健康
通过。原串并发基线创建 36/48 个 run 后，因预算扇出及并发实例租约失效暂停；[历史部分实测和初始 O1-R 卡](o1-live-baseline.md)保存失败证据与用量，后续批准/执行见下文。正式研究进度、主机 WHEA 风险和人工复核等剩余门槛见[O1 执行断点](o1-execution-status.md)。不能以已获额度代替
环境稳定、人工评分或基线完成。

2026-09-16 用户追加执行约束：单 case 稳定成功前停止 12-case 付费并发和整组串行，优先离线复现/最小修复及逐次单 case 验证，不自动排队多例。达到单 case 验收后仍需用户确认恢复批次；原额度不是自动续跑许可。追加约束时修复/分配尚待确认，后续批准与结果如下。

用户随后确认实施 O1-R：按 [单 case 可靠性协议](o1r-single-case-reliability.md)实施预算扇出与实验恢复保护最小修复、实例锁等待时钟修正，完成离线验收及独立复审后逐次单 case 验证；不授权恢复批次或扩大硬预算。

O1-R 本轮最小修复及执行样本观察完成：最新候选三开发例各两次 6/6 completed、最终 token 完整；含补修前一例累计占用 7，新总额度 43/48，剩余 5。该样本支持冻结隔离环境的单 case 执行可靠性，来源仍 degraded、严格 JSON/冷启/语义/并发/硬件稳定未验收；[安全记录](o1r-single-case-observations.json)与原基线分母分开。付费批次和剩余额度自动使用继续禁止，恢复须用户重新确认。

用户随后授权 O1 缓存成本拆账与已有开发报告助手核验：只补计数观测，不改研究 Prompt/预算/检索调度；只核验六份 P01/P06/P07 最新报告，保留集封存，标签 assistant_review/非盲评/未人类校准。已知输入热点及关键声明问题见 [拆账](o1-cache-cost-accounting.md)与 [核验](o1-development-report-review.md)。原子声明完整支持率未统计，O1 仍未完成；六源限流离线修复/真实复测另按用户方向，不自动进入 O2 或恢复批次。

工程基础实施范围在 PR 5-2 后结束。先完成上述模型适配；后续效果优化需要依据真实运行数据
重新确认，建议顺序为：先冻结少量
代表性 case 与重点指标基线，再做针对性优化和回归验证，最后才整理可复现演示、架构讲解与面试
材料。上述工作不自动启动，也不属于 PR 5-2 的验收内容。

2026-09-17 继续用户已明确授权的 O1 六源限流离线诊断/修复：仅限检索 provider 出站共享准入、
请求间隔、冷却和必要超时/兼容适配，见 [限流审计](o1-retrieval-throttle-audit.md)。这是本次
授权的出站范围修订，不包含下面排除的企业级入口限流/分布式队列。不得因此恢复付费批次或进入 O2。

2026-09-17 用户授权实施 O1-A（评估口径收口），协议升级 [v4](product-effectiveness-optimization.md)，
原案例/参考/rubric/并发阈值不变；补既有六份开发报告逐处台账及评审资格，
历史诊断与新候选正式配对分开。新 [O1 任务卡](o1-next-steps.md)取代原未实现部分的默认顺序：
A 收口 → B 离线单例资格 → C 另授权冷启单例 → D 另授权新正式配对 → E 闭环/假设。
当时只有 A 获实施授权；后续 B 授权如下，不恢复付费批次、不使用剩余 5、不进入 O2。

2026-09-17 用户授权 O1-B 批次前观测，并明确批准最小补修 run/实例租约等待后重新取时、
冷加载移出事件循环及 health 对过期 lease fail closed。观测覆盖严格 JSON/结构/修复 parser
次数/finish_reason 与失败分类，停服取消保持 owner-scoped 清理；详见
[O1-B 记录](o1b-prebatch-observability.md)。不改 Prompt、冻结案例、single-worker/fencing 或硬预算。
离线验收不等于真实冷启、主机稳定或批次资格；当时 C～E 仍须相应新授权。

2026-09-17 随后用户授权 O1-C 真实单例验真，本次 P01 一次提交上限。
实际停在真实前置：网络健康 4/5，community gate 不可用（代码推断，具体反馈未知），
routed Tavily POST 通过；LLM/冷启/研究/报告未执行。新 run 0、累计 43/48 不变。
[停止记录](o1c-single-case-verification.md)保留失败与 unknown；下一步先确认 community 可用性，
前置重查和单例继续须明确授权，不自动补跑，不启动 D/E/O2 或批次。
本轮离线回归另有 53 passed / 1 failed（缩放调度间隔断言），单项复查通过；
首次失败不抹除，时序不稳定未修复，当前不能宣称全绿。先定位后再讨论真实准入。

O1-C 后续已获诊断授权，见 [两项阻断定位](o1c-blocker-diagnosis.md)：社区返回限流错误，
健康 probe 未带已配置 key；离线时间断言存在低分辨率时钟与准入/调用打点错位。
本轮仅诊断，无产品/测试修复或新研究；最小修复与真实准入按范围另确认，批次/O2 不恢复。

随后用户明确授权统一社区探测凭据、确定性时序测试与准入/调用节拍契约。改动只复用已有
可选 key，静态规格不存凭据；虚拟时间替代缩放墙钟断言，原门算法、通道与预算不变，
见 [运行契约](phase1-runtime-contract.md)。本轮只离线验证，不重查来源或提交 P01；
真实来源可用性、冷启单例、质量/并发门仍未通过，43/48 不变，批次/O2 不恢复。

2026-09-17 用户重新授权完整前置并执行 P01 一次：冷启 completed，93.14 秒、24,198 token，
六源 success 6/6（community 0 结果），无记录外部失败/重试或观测租约丢失。累计 44/48，
隔离服务正常停止；[单例验真](o1c-single-case-verification.md)记录身份、成本、资源风险和
知识物理 hash 准备异常的受控处理。报告仍有无关来源、异常标题与引用问题；语义评分和
批次资格未通过。下一步仍在 O1，先离线追踪此报告缺陷，另确认修复/验真范围；
不自动补跑、排队、恢复整组串行/12-case 并发或进入 O2。

用户随后授权 C 问题收口：实现显式候选词法准入、缺失题名标记、删除无依据互证与
明确唯一引用补链；冻结 source-score-v2 / what-why-how-v2，旧 manifest 可读但跨版本
同 run 恢复拒绝。支持状态与安全 fetch 不变，原报告缺引用和网络 unknown 不猜测改绿。
[验真记录](o1c-single-case-verification.md)保存离线回归与残余边界。额度仍 44/48，
用户进一步授权 C 的缺引用/unknown 离线收口：synthesis v2 明确逐子句引用及无支撑断言处理，
安全失败只补脱敏固定分类、不绕过拒绝或跨句补引；真实模型效果尚未验证。
下一步先单独确认安全传输适配契约与范围，离线验收后再确认一例新 run；
不自动补跑、启动配对批次或进入 O2。任务细分见 [O1 剩余任务卡](o1-next-steps.md)。

2026-09-18 用户明确批准 C2 最小安全代理离线实现与验收：显式 opt-in、默认关闭，仅匹配
用户信任的固定 loopback HTTP CONNECT 端点，无认证，动态目标仅 HTTPS:443。CONNECT
目标/Host 使用本地验证的公网 IP，内层 Host/SNI/证书校验使用原域名；逐跳验证、握手累计
有界、取消清理，保留响应/预算/节拍限制和 no fallback。依赖获批准的代理遵守目标，不能
证明恶意代理的实际远端连接；self-forward、远程/SOCKS/HTTPS 代理、HTTP 引用不在范围。
新增配置与 immutable 安全身份、离线回归/全套验证、独立复审和本地提交属于本次授权。
具体契约见 [运行契约](phase1-runtime-contract.md)，验收记录见 [C 维护记录](o1c-single-case-verification.md)。
C2 已完成离线实现、完整验证和独立复审；这不证明真实代理互通或报告效果通过。
本次不启用配置、不做真实健康/LLM/API/case，不恢复批次、不进入 O1-D/O2、不推送；
当时 C3 单例需另批准调用/费用边界，研究额度仍为 44/48；随后获批前置的停止事实见本文开头。

## 5. 不在当前实施范围

以下内容不再安排当前 Phase，也不作为当前稳定版门禁：

- 多用户认证、租户 ownership、RBAC/SSO、API key middleware 和企业级入口 rate limiting。
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
