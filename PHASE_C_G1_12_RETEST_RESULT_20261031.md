# Phase C 12 例分层 G1 复测（2026-10-31）

> 未跑 200。目标：验证 conditional top-option claim-support 告警是否真正改变默认分支。

## 1. 运行

- 代码 HEAD：`090cec5`
- 样本：同一 12 例分层开发集
- 12/12 complete
- tokens：**828,748**
- health（修正后）：9 warn / 0 invalid
- official 正文页：44

说明：运行后存储的 batch_health 有 5 invalid，原因是 `report_claim_support:*`
被错误当成 hard invalid；已修正 batch_health 分类，claim-support 现为 warn 诊断。
修正后读取为 0 invalid。

## 2. 内容结果

| 指标 | 上轮 12 例 | 本次复测 |
|---|---:|---:|
| usable | 12/12 | 12/12 |
| decision-grade | 10/12 | **6/12** |
| C4 | 0 | 0 |
| C2 partial | 2 | **6** |

## 3. 关键发现

这次不是“复审更严格”这么简单，而是暴露了 Phase C 的架构限制：

1. claim-support flags 正确触发：
   - F200-021/117/158：`conditional_top_option_owner_dominates`
   - F200-198：`conditional_top_option_secondary_dominant`
   - F200-183：`recommended_winner_owner_dominates`
2. 但 self-review **不能改变排名/默认分支**：
   - 它的 correction 合同只能改字段文本，或用 `withdraw_decision` 撤掉整个决策；
   - 没有“把 #1 降级为假设但保留其他分支”的动作；
   - 结果：
     - F200-021/104/117：flag 存在，self-review 0 修正或只改措辞；
     - F200-158：self-review 未运行（checks_not_six）；
     - F200-183：recommended + winner-owned flag 仍在，self-review 只加“本次材料范围内”；
     - F200-198：默认 Buildah 排序未改。

因此：

> claim-support 现在能**发现问题**，但 self-review 机制**没有能力执行对应的排序降级**。

## 4. 结论

Phase C 仍未闭环，且这次复测说明继续调 self-review prompt 本身不够：

- 需要在结构层增加“降级/撤回默认排序”的能力，或
- 在 self-review 之后加确定性后处理规则。

## 5. 建议下一步（零付费）

优先实现 **post-review 结构性 guard**：

### A. recommended + `recommended_*` flag

- 将 recommended 降级为 conditional 或 insufficient_evidence；
- 清空 winner；
- 保留 ranked_options/trade_offs，但在 recommendation 中标注“证据不足以支持唯一推荐”。

### B. conditional + top-option flag

- 保留条件分支，但移除/降级“默认 #1”的确定表述；
- 在 recommendation/证据摘要中明确“默认分支仅为待验证假设”；
- 不改变候选内容，只改变决策强度。

实现后再做 12 例复测；不跑 200。

当前没有付费任务在跑。

## 6. 后续零付费实现：结构性 decision guard

新增 `utils/decision_guard.py`，并在 synthesis 与 self-review 后执行：

- `recommended` + `recommended_*` claim flag：
  - 有 ≥2 ranked options → 降级为 `conditional`，清空 winner；
  - 不足 2 个选项 → 降级为 `insufficient_evidence`；
  - recommendation 添加“证据强度校准”说明；
- `conditional` + top-option owner/secondary flag：
  - 保留分支；
  - recommendation 添加“默认/排序靠前分支仅为待验证假设”的强度校准说明；
- 幂等，不重复添加标记。

对本次 12 例 snapshot 做只读 dry-run：

| case | 原状态 | guard 动作 |
|---|---|---|
| F200-183 | recommended | recommended → conditional |
| F200-021 | conditional | top-option strength caveat |
| F200-117 | conditional | top-option strength caveat |
| F200-158 | conditional | top-option strength caveat |
| F200-198 | conditional | top-option strength caveat |

其余 7 例不变。新增测试覆盖 guard 幂等/降级/条件说明。

## 7. 下一步

需要对同一 12 例再做一次复测（约 0.83M tokens），确认 guard 后：
- F200-183 不再是 recommended；
- 4 个 conditional 的默认分支表述被降级；
- DG/C2 是否改善，是否引入过度拒绝/C4。
不跑 200。
