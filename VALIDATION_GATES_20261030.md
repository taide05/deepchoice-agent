# 质量迭代的验证门槛（2026-10-30）

> 目的：避免“改一行代码就跑一次 200 例”。200 例是**发布级测量**，不是开发反馈手段。
> 依据已有成本：最终 200 主批 + 替换约 12.65M tokens、7.5 小时；不能作为每次改动的回归测试。

## 1. 三层验证

### G0：确定性/离线层（默认每改动都跑）

适用范围：

- renderer / citation ledger / 标签 / schema / 后处理；
- 任何不依赖模型新输出的改动。

做法：

1. 单元测试、合同测试；
2. 用现有 200 个 snapshot 做**离线重放**；
3. 检查不变量：
   - body/reference/ledger 一致；
   - raw/malformed marker；
   - 空 ranked / truncated unresolved；
   - 官方/厂商/社区标签；
4. 不调用外部 API，不产生付费 tokens。

放行：G0 全绿才进入 G1。

### G1：小规模行为验证（一次改动只跑一次）

适用范围：

- prompt / synthesis / retrieval / ranking 行为变化。

做法：

- 固定开发集：**20 例 expanded 开发集 + 6 例 independent**（必要时加 2 例失败复测）；
- 每个“改动 bundle”只跑一次，不逐 commit 跑；
- 评审：C1–C4 + 契约 flags + 引用/来源标签；
- 预算上限：**2.0M tokens**；
- 若出现 C4、空报告、contract invalid、来源引用严重退化：停止，不进入 G2。

### G2：正式 200（发布级，极低频）

触发条件：

- G0/G1 全绿；
- 改动 bundle 已冻结（代码 HEAD、prompt、retrieval 配置、learned_docs SHA）；
- 用户单独批准时间窗口与预算。

做法：

- 按已冻结的 10 批 ×20 例执行；
- 200/200 全量评审；
- 固定分母 200，允许按 v1.1 替换/补跑并披露；
- 预算上限沿用 15.0M tokens（主批）；替换另报；
- 每次正式 200 结果作为一次不可混用的测量；不因后续小改动自动重跑。

## 2. 改动 bundle 规则

- 不按“改一点代码”开 G2；
- 一次 bundle 只包含同一主题的改动：
  - E1：citation/contract/label；
  - E2：retrieval/official coverage；
  - E3：synthesis/claim support；
  - E4：evaluation/rubric；
- bundle 冻结后先 G0，再 G1，再决定是否 G2；
- bundle 期间不插入新的行为改动，避免验证对象漂移。

## 3. 开发集与最终 200 的关系

- 最终 200 的**逐例结果不用于逐例调参**；
- 已建立的 20 例 expanded 开发集和 6 例 independent 是开发反馈集，不进入正式 200 指标；
- 若未来把最终 200 中某些 case 用作调参，必须在结果中披露“开发/测量重叠”；
- 正式 200 只报告一次冻结版本的结果，不把多次运行拼成“更好看的 200”。

## 4. 成本上限

| 层级 | 频率 | 预算/次 |
|---|---|---:|
| G0 离线/单元 | 每次改动 | 0 |
| G1 小规模行为 | 每个 bundle 1 次 | ≤2.0M tokens |
| G2 正式 200 | 每个 release candidate 1 次 | ≤15.0M tokens |

超过上限或出现 C4/contract invalid → 停止并单独报批。

## 5. 当前状态

- 最终 200：已冻结，内部结果不变；
- Phase A：已完成；
- Phase B：尚未开始；只有通过 G0 + G1 后才考虑是否需要一次 G2；
- 默认不做“改一点代码就跑 200”。
