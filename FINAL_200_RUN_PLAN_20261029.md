# 最终 200 运行计划（冻结草案，2026-10-29）

> 状态：**未批准、未运行**。本文件冻结名单/配置/预算/窗口方案，等待用户单独批准。
> 题集与验收口径按 `FORMAL_ACCEPTANCE_PROTOCOL_20261028.md` v1.1。

## 1. 冻结名单

- 题集文件：`.scratch/cases/cases_formal_200.json`
- 文件大小：174,035 bytes
- SHA-256：`46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807`
- 案例数：**200**（唯一 ID 200，无重复）
- 构成：50 个候选对 × 4 场景（solo/team/enterprise/migration，各 50）
- 类别分布：
  - Infra 32、Backend 28、Database 24、Frontend 20、AI/ML 20、CI/CD 16、
    Observability 12、Data 12、Python 12、Messaging 8、Security 8、Containers 8
- 冻结方式：**不复制、不改写**；最终运行直接使用该路径 + 上述 SHA；
  运行前再次用脚本核对 SHA，若不一致立即停止。
- 组成政策：**优先单批完整 200 例**；协议 v1.1 允许由多次运行/不同版本/替换/补跑组成，
  因此单批不是硬门。若出现基础设施中断/无效例，按 v1.1 替换/补跑，保留每个 case 的
  provenance、失败和替换披露；分母始终为 200。
- **分批保存（防止中途丢失已完成例）**：200 例拆成 **10 个固定批次 × 20 例**；
  - 批次清单目录：`.scratch/cases/final_200_batches_20261029/`
  - manifest：`manifest.json`，SHA-256
    `fe13df3720c3f990fa9f7d63680f0aa8ab6eb721635b8e78ac89901533205478`
  - 分配方式：按 scene 分层（每批 5 个 scene）+ 固定 seed `20261029` 的确定性打乱；
    每批 20 例、覆盖 8–12 个 category；
  - 每题只出现在一个批次，10 批合计 200 个唯一 case；
  - 每批文件与 SHA 见下表；批次顺序固定 01→10，不按结果重排。

| 批次 | 例数 | scene (solo/team/enterprise/migration) | 覆盖 category 数 | 批次文件 SHA 前缀 |
|---|---:|---|---:|---|
| 01 | 20 | 5/5/5/5 | 9 | `d4d79559ba0229e9` |
| 02 | 20 | 5/5/5/5 | 9 | `ae98405de3ca8c20` |
| 03 | 20 | 5/5/5/5 | 10 | `c69dd41bdfeee18a` |
| 04 | 20 | 5/5/5/5 | 9 | `bfbe17160bcc9cd6` |
| 05 | 20 | 5/5/5/5 | 10 | `e00ed795adb3753e` |
| 06 | 20 | 5/5/5/5 | 8 | `0d4ef43211993842` |
| 07 | 20 | 5/5/5/5 | 10 | `05c73ccf631aa52c` |
| 08 | 20 | 5/5/5/5 | 10 | `9f275d83ff7f3db9` |
| 09 | 20 | 5/5/5/5 | 12 | `3c43fe62d3403912` |
| 10 | 20 | 5/5/5/5 | 8 | `8771f98a04e46e06` |

- 每批单独运行、单独输出目录（`final-200-batch-01`…`10`），完成即落盘；
  中断时已完成批次/报告保留，不覆盖、不删除。后续只补未完成批次或协议允许的替换。

## 2. 代码与运行配置

- 工作树：`D:\deepchoice-precodex`，分支 `precodex/deepseek-adapter`
- 代码 HEAD（计划时）：`499c9b2`；计划/文档提交后的实际 HEAD 在执行前用
  `git rev-parse HEAD` 重新记录；执行前确认无未提交代码改动
  （`learned_docs.json` 是运行时数据，记录 SHA 后以只读模式运行）
- 零跑例预检已完成：题集 SHA 与 200 唯一 ID 复核、8100 端口空闲、磁盘充足、
  learned_docs SHA 记录；LLM 余额/健康检查在执行时由 batch 预检执行
- `learned_docs.json`：22,385 bytes，SHA-256
  `de28babb021edc6911902b460239107bdf621bae0ac20c9c0aaceb2d63b70930`
- 运行参数：
  - 模型：`deepseek-flash`
  - concurrency：**2**
  - `COMMUNITY_RETRIEVAL_MODE=evidence_pack`（默认）
  - `LEARNED_DOCS_READONLY=1`（禁止运行中改写 learned docs）
  - 单 case timeout：1800s
  - 余额预检：默认开启（失败则不启动任何 case）
  - `run_limits.py` 默认限制保留并记录实际参数
- 输出目录（建议）：`.scratch/cases/runs/final-200-<日期>`
- provenance 记录：
  - case 文件 SHA、代码 HEAD、learned_docs SHA
  - 模型、并发、环境变量
  - 每 case 的 started/tokens/wall/status/health
  - batch_meta / batch_health / summary

## 3. 预算估算

基于当前代码近期批次（C2/community/渲染修复后）：

| 批次 | cases | tokens | 每例平均 |
|---|---:|---:|---:|
| 20 例扩大验证 | 20 | 1,212,857 | 60,643 |
| C2 10 例验证 | 10 | 659,895 | 65,990 |
| 独立 6 例复测 | 6 | 374,260 | 62,377 |
| 可靠性 2 例 | 2 | 131,342 | 65,671 |

- 每例估计：**60k–66k tokens**
- 每批（20 例）中心估计：**约 1.2–1.4M tokens**；单批异常上限建议 **1.8M tokens**
  （达到即停止检查，不硬跑）
- 200 例中心估计：**约 12.1–13.2M tokens**
- 建议批准**主批预算上限**：**15.0M tokens**（10 批累计，含主批重试/长尾余量）；
  若主批后仍需替换/补跑，超出 15.0M 的部分应单独报批，不把 15.0M 当无限预算。
- 旧基线（2026-10-26）：10,618,062 tokens；当前代码不同，不能直接当成本承诺。
- 货币费用取决于实际单价，不在本计划中虚构。

## 4. 时间与窗口

- 按近期 concurrency=2 的吞吐：20 例约 40 分钟；10 例约 21 分钟；
  估计 200 例 **6.5–7.5 小时**（含长尾），保守计划 8 小时。
- **具体运行窗口由用户决定**；本计划不预定日期/时段。运行应完整落在用户指定的窗口内；
  运行期间不并行其他付费任务。中断后按 v1.1 补跑/替换。

## 披露范围（重要）

- 本计划中的“披露”指**内部验收报告/内部 provenance 记录**，用于验证指标与可复现性；
  **不是对外发布**。
- 内部记录（case→批次、commit、日期、替换、失败、tokens）保留在 `.scratch` 与内部报告中；
  不 push、不 upload、不自动外发。
- 外部交付材料只在你明确要求并确认口径后单独生成；默认**不包含**内部批次/替换/失败细节。
  我不会主动把内部记录写进对外材料。
- 无论内部/外部，不用“平均值”掩盖 C4；外部材料如需写结果/限制，按你确认的措辞，
  不会声称未经内部验证的“单版本、无替换、200/200 完美”状态。

## 5. 执行步骤

1. **冻结检查**（零跑例）
   - 校验 master SHA、200 个唯一 ID、10 个批次文件 SHA、代码 HEAD、learned_docs SHA；
   - 全量测试通过；
   - LLM 余额预检、8100 端口空闲、磁盘/日志路径可用；
   - 确认默认 `evidence_pack`、`LEARNED_DOCS_READONLY=1`。
2. **按批次运行（固定 01→10）**
   - 每批独立命令、独立输出目录，concurrency=2，timeout 1800；
   - 每批运行前做余额预检；每批完成后检查 summary/health/完整性并落盘；
   - 记录 batch_meta（本批 case SHA、master SHA、HEAD、learned_docs SHA、配置、tokens）；
   - **一批结束才启动下一批**；中途故障不覆盖已完成批次。
3. **批间检查与停止**
   - 每批后：invalid、community 失败、token 使用累计；
   - 若出现系统性失败/严重质量异常，停止后续批次，不硬跑；
   - 已保存报告保留；按协议决定修复、替换或补跑，并记录 provenance。
4. **完整性检查**
   - 10 批 ×20 例是否为 200 个报告单位；
   - 缺失/invalid/失败列表；
   - 必要时按 v1.1 替换/补跑，记录 provenance；
5. **200/200 全量内容评审**
   - 逐份 C1–C4；community/引用质量/来源标签；
   - C4 或空报告 → 修复/替换/重跑并披露；
   - 汇总 usable / DG / C4 数、状态分布、token/时间、失败/替换。
6. **最终报告与交付材料**
   - 可复现指标、限制、失败与替换、实际成本；
   - 不把本轮任何开发期验证当作最终成绩。

## 6. 需要用户批准的事项

- [ ] 冻结名单 SHA `46728f...` 与 10 批拆分（manifest SHA `fe13df...`）不再改动
- [ ] 主批预算上限 **15.0M tokens**；替换/补跑超出部分另行报批
- [ ] 允许正式执行最终 200（**时间窗口由用户指定**，计划不自行预定）
- [ ] 评审/替换政策：200/200 全量评审；按 v1.1 在**内部**记录替换/补跑与 provenance，
      C4 先修复/替换，不用平均值掩盖；对外材料不含内部批次/替换细节（除非你另行确认）

> 单批不是硬门：协议 v1.1 允许 mixed runs/replacements；如中断可补跑，但必须披露。

## 7. 风险与停止条件

- LLM 余额/限流、StackExchange/Tavily/官方页面外部故障：按 health gate 记录；
  大面积失败时中断，不硬跑；
- community 预计仍有少量外部失败（近期复测 6/6、2/2，但不保证）；
- 200 例长尾/替换可能导致实际时长/成本高于中心估计；主批达到 **15.0M tokens** 前停止并请示；
- 运行结束前不宣称最终指标；最终成绩只在 200/200 全量评审后产生。

## 8. 批次文件校验

- 批次目录：`.scratch/cases/final_200_batches_20261029/`
- manifest SHA：`fe13df3720c3f990fa9f7d63680f0aa8ab6eb721635b8e78ac89901533205478`
- 已核对：10 批 ×20 例，合计 200 个唯一 case；每批 scene 5/5/5/5；
  每批覆盖 8–12 个 category；master SHA 与协议一致。
- 每批运行命令模板（示例 batch 01）：
  `run_batch.py --cases .scratch/cases/final_200_batches_20261029/batch_01_cases.json --out .scratch/cases/runs/final-200-batch-01-<日期> --concurrency 2 --timeout 1800`
