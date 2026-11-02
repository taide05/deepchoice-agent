# DeepChoice 最终 200 评审 — 新会话交接（2026-11-02）

> 用途：带着本文件开一个新会话继续 **只做 200/200 内容评审与最终汇总**。
> 不要重跑最终 200，不要改代码/prompt/retrieval/guard，不要重新生成报告。

## 1. 工作树与冻结状态

- 开发树：`D:\deepchoice-precodex`
- 分支：`precodex/deepseek-adapter`
- 当前 HEAD：`b4b9b0a`
- 最终 200 运行代码基线：`adecccb`（产品代码 `c8fad27`）
- 题集：`.scratch/cases/cases_formal_200.json`
- 题集 SHA-256：`46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807`
- 运行状态：**200/200 唯一 case 跑完，不重跑**
- 3 个替换：F200-058、F200-187、F200-126
- 最终 200 运行目录：
  `.scratch/cases/runs/final-200-20261031b/`
- 完整产物、report.md/snapshot.json 均在上述目录。
- 运行完成记录：`FINAL_200_RUN_COMPLETE_20261101.md`
- 原始 token 消耗：
  - 10 批主运行：12,675,181
  - 含替换/canary：13,068,148
  - 含失败旧批总账：14,344,100
  - 15M 上限剩余 655,900
- **后续不再有付费 batch 运行。**

## 2. 评审进度（最重要）

评审文件目录：
`.scratch/cases/runs/final-200-20261031b/reviews/`

已完整保存：

| 文件 | case 范围 | 数量 |
|---|---|---:|
| chunk-01.json | F200-001..010 | 10 |
| chunk-02.json | F200-011..020 | 10 |
| chunk-03.json | F200-021..030 | 10 |
| chunk-04.json | F200-031..040 | 10 |
| chunk-05.json | F200-041..050 | 10 |
| chunk-06.json | F200-051..060 | 10 |
| chunk-07.json | F200-061..070 | 10 |
| chunk-08.json | F200-071..080 | 10 |
| chunk-09.json | F200-081..090 | 10 |
| chunk-10.json | F200-091..100 | 10 |
| chunk-11.json | F200-101..110 | 10 |
| chunk-12.json | F200-111..120 | 10 |
| chunk-13.json | F200-121..130 | 10 |
| chunk-14.json | F200-131..140 | 10 |
| chunk-15.json | F200-141..144（**只写了 4 条，不完整**） | 4/10 |

当前状态：

- **完整评审：140/200**
- 半成品：chunk-15 的 4 条（F200-141..144）
- 未评审：F200-145..200（56 例）
- 建议：**不重用 chunk-15 的半成品，直接重跑 F200-141..150 的完整 chunk-15**，保证 10 条同批次一致性。
  这样剩余需要：F200-141..200 共 **6 个 chunk（15..20，60 例）**。
- 也可以先校验 chunk-15 的 4 条，再只补 145..150；但为一致性和简单，建议重跑 chunk-15。

## 3. 评审输入与规则

评审 map：
`.scratch/cases/runs/final-200-20261031b/review_map.json`

紧凑输入（每例一份）：
`.scratch/cases/runs/final-200-20261031b/review_inputs/F200-XXX.json`

生成脚本：
`.scratch/cases/build_review_inputs_20261101.py`

每个 case 的评审必须：

1. 读 `report.md` 全文；
2. 读对应 `review_inputs/F200-XXX.json`（任务、final_recommendation、quality signals、source 状态、冲突、citation bindings）；
3. 不联网；
4. 不改 report/snapshot；
5. 只写 `reviews/chunk-NN.json`。

评分：

- C1 核心回答；
- C2 证据适用性（vendor-only/secondary-only 默认排序不能算已证实；`has_body=false` 只算导航/元数据，不算证据）；
- C3 条件/缺口；
- C4 致命错误（编造、候选身份/归属错误、矛盾、无效状态、危险断言）；
- `usable = C1 met && C4 == 0`
- `DG = usable && C2 met && C3 met`

## 4. 新会话继续方式（必须小 checkpoint）

服务器此前 OOM 崩溃过两次，根因是 DSH Node 进程默认 4GB 堆 + 老会话过大 + 并行 workflow 峰值。

新会话必须：

- 使用 **新会话**，不要续这个 6 周老会话；
- 评审 workflow **最多 3 个 agent 并行**；
- 每次只做 **3 个 chunk（30 例）**，完成立即落盘；
- 每轮完成检查文件数和 case 数；
- 不跑 10-agent fan-out。

建议拆分：

| 轮次 | chunk | case |
|---|---|---|
| 1 | 15,16,17 | F200-141..170 |
| 2 | 18,19,20 | F200-171..200 |

（chunk-15 重跑覆盖 F200-141..150，替换半成品。）

## 5. DSH 崩溃处理选型（建议采用组合 A）

用户提供的诊断与建议中，建议采用：

### 立即做（低风险）

1. 完全退出 DSH 桌面版；
2. 设置用户级环境变量：
   ```powershell
   [Environment]::SetEnvironmentVariable('NODE_OPTIONS','--max-old-space-size=6144','User')
   ```
   16GB 机器上保守选 6144；8192 也可用但偏紧。
3. 重新打开桌面版；
4. 启动 **DSH-Guard**，确认其“崩溃检测 + 自动重启”生效；
5. 开新会话，使用本 handoff。

### 评审期间

- 只开 3-agent/3-chunk 的小 workflow；
- 每轮落盘后再继续；
- 不并行 10 个 agent；
- 如 RSS 再次接近上限，先完成当前 chunk，再重启 DSH。

### 之后再做（不要现在）

- 修改 `desktop/src/launcher.cjs` 永久提高堆上限/异常重启；
- 或升级核心到 0.2.1-rc.5；
- 这些要等评审和最终汇总完成后再做，避免中途 rebuild 打断。

不推荐现在只做“改 launcher + rebuild”而不加内存变量，因为 rebuild 本身会打断当前会话；先用环境变量 + guard 度过评审。

## 6. 剩余交付物

评审完成后：

1. 合并 `chunk-01..20`：
   - 校验 200 个唯一 case、无缺失/重复；
   - 汇总 C1/C2/C3/C4、usable、DG；
   - 汇总 community 使用、official 覆盖；
2. 生成最终结果文档：
   - 总 case 200；
   - usable / DG 数量与比例；
   - C4 数量；
   - 失败/partial 案例清单；
   - 与上一轮最终 200 的对比（可选）；
   - 替换披露：F200-058、F200-187、F200-126；
3. 不改报告、不重新生成、不重跑 batch。

## 7. 关键文件

- `FINAL_200_RUN_COMPLETE_20261101.md`
- `FINAL_200_FREEZE_20261031.md`
- `FINAL_200_9BATCHES_STATUS_20261101.md`
- `.scratch/cases/runs/final-200-20261031b/review_map.json`
- `.scratch/cases/runs/final-200-20261031b/review_inputs/`
- `.scratch/cases/runs/final-200-20261031b/reviews/`
- `DSH-服务器崩溃诊断-2026-11-01.md`

## 8. 当前没有付费任务

- 无 batch 运行；
- 无 workflow 在跑；
- 新会话只做只读评审和文件写入。

## 9. 后续工作范围（评审之后）

以下事情**尚未定下来**，但新会话必须知道它们是候选后续，不得擅自默认执行：

1. 合并 200/200 评审，生成最终验收结果；
2. 决定是否把新结果与旧最终 200（10/29）做对照；
3. 决定是否做报告形态/长度优化（此前 backlog）；
4. 决定是否对外交付、对外口径如何写；
5. 决定是否继续改代码（改代码会使本次最终 200 指标失效）；
6. 决定是否升级 DSH 核心或永久修改 launcher。

每一步都需要用户明确确认，不要自己选方向。

## 10. 必须遵守的范式与规则

即使后续目标未定，这些约束不变：

### 指标与验收

- 禁止编造或美化指标；
- 必须报告 C2/C3 partial、C4、不可用案例，不能只报总数；
- `usable = C1 met && C4 == 0`；
- `DG = usable && C2 met && C3 met`；
- 任何 C4 > 0 的 case 视为不可用，不能静默忽略；
- 200/200 全量评审，不抽样。

### 最终 200 冻结

- 本次最终 200 已运行完毕，不重跑、不重新生成；
- 不因后续小改动重新 review 这 200 份报告；
- 3 个替换必须披露：F200-058、F200-187、F200-126；
- 旧最终 200（`final-200-20261029`）保持不动，不覆盖；
- 任何新最终 200 必须用新运行目录，并重新获得用户批准。

### 代码与验证

- 评审期间不改 prompt/retrieval/guard/报告形态；
- 如果之后改代码，旧 200 指标不能直接归给新代码；
- 继续遵守验证阶梯：
  - G0：零成本/离线；
  - G1：小规模行为集；
  - G2：正式 200 仅用于冻结的 release candidate；
- 不为小改动重跑 200；任何正式 200 都需要明确批准、预算和窗口。

### 成本与运行

- 任何付费运行都必须先说明目的、案例数、token 预估，并取得批准；
- 主批预算上限按用户批准执行；不得悄悄超预算；
- 替换/补跑按 v1.1 披露，不能当成普通 case；
- 评审本身是只读工作，不产生新的 batch 费用。

### 数据与 provenance

- 保留运行目录、HEAD、题集 SHA、替换记录；
- 不删除/覆盖旧报告和 snapshot；
- 评审 chunk 必须落盘，不能只留在上下文里；
- 新会话先确认文件数量再继续，不靠记忆。

### 外部披露

- 默认内部使用；
- 不 push、不 upload、不对外发布；
- 对外数字、口径、材料必须用户明确确认；
- 不把 `.env`、token、密钥、内部 provenance 写进外部材料。

### 安全

- 不在聊天/日志/截图中输出 token；
- `.env` 位于 `D:\deepchoice-agent`，不提交；
- 失效 token 用匿名 fallback，但要注意匿名 GitHub 限额。

### DSH 稳定性

- 新会话不要续这个 6 周老会话；
- 评审 workflow 最多 3 个 agent 并行；
- 每次 3 个 chunk，完成即落盘；
- 不跑 10-agent fan-out；
- 每轮检查 RSS/文件数；接近堆上限先收尾再重启。

## 11. 已知 backlog（尚未决定是否做）

- 报告过长：可做“决策摘要 + 证据附录”分离；
- 官方覆盖残余：JS/导航站、403、ConnectError；
- 部分 case 的 C2 证据缺口（真实缺口，不能靠规则修）；
- claim-support 目前是 decision-field 级，未到逐句 claim；
- 旧 snapshot 方括号标题 artifact；
- Phase A 的 registry canonical merge / 噪声来源硬排除；
- 外部交付材料；
- launcher 永久提高堆上限 / dsh-guard 自启 / 核心升级。

## 12. 新会话第一步

1. 读本文件；
2. 检查 `reviews/` 中 chunk-01..14 完整、chunk-15 归档；
3. 重跑 chunk-15（F200-141..150）；
4. 按 3 个 chunk 一轮完成 chunk-16..20；
5. 合并 200/200，先报指标，再讨论后续方向。

