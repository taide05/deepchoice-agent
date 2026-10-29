# Community 20 例开发反馈：迭代记录（2026-10-29）

> 20 例是**开发反馈集**，不是验收集；以下改动只修可归因的失败类别，不用它调排名权重/阈值，
> 避免过拟合。

## 1. 数据显示

- 20/20 complete，约 40 分钟（concurrency=2）；
- community 有 pack：16/20（80%）；
- 报告实际引用 Stack Overflow：14/20（70%）；
- community 外部失败：4/20（20%）：1 个 ReadTimeout，3 个 `no outbound channel`；
  health 记为 `optional_source_failed`，未导致 invalid；
- 有 pack 但未引用：2 例（F200-006、F200-158）；两例的 pack 已进入 evidence chain，
  是综合模型未使用，不是抓取/评分失败；
- raw citation 0、空括号 0；community 未造成 invalid；
- tokens：1,212,857 vs 同 20 例旧基线 1,020,580（+18.8%）；中位 +6,403/例；
  这是跨版本比较，不能全部归因 community；单例配对 context 增量约 +5.2%。

## 2. 已做的优化

### 2.1 可靠性：有界重试（已实现）

- `community_evidence._community_client()`：2 → 3 次尝试，1.5s/3.0s 退避；
- `_request_json()`：对 timeout/transport/RuntimeError 与 429/5xx 均最多 3 次尝试；
- 只改基础设施重试，不改变查询/评分/选择逻辑；
- 提交 `b612f70`；新增 outbound retry 测试；无真实网络测试。

### 2.2 明确不做的优化（避免过拟合）

- 不因 F200-006/F200-158 未引用而强制 synthesis 引用社区，或修改权重；
  两例 pack 已在 chain 中，属于模型判断；
- 不因 20 例 token +18.8% 缩减 pack 数量/正文上限；尚未隔离版本/输出波动；
- 不因 20 例命中率调整查询词表；命中率受主题/Stack Overflow 覆盖影响；
- 不在同一 20 例上反复调参后宣称泛化。

## 3. 下一步

1. 对这 20 份报告做完整内容审阅（C1–C4、社区引用相关性/标注）；
2. 需要时用独立样本或最终 200 验证重试/默认行为；
3. 最终 200 仍未批准/未运行；20 例不作为最终成绩。

## 4. 当前判断

- community 源从 0 结果/不可引用变为 80% pack、70% 引用，方向可用；
- 20% 外部失败仍偏高，但非阻断；重试优化待下一批验证；
- 默认保留 `evidence_pack`，`legacy` 可回退。
