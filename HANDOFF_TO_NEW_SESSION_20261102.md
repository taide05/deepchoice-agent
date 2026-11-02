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
