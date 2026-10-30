# Phase C：claim-level evidence support（2026-10-30）

> 目标：让“决定性结论是否有可追溯、适用来源”成为可检查的 claim-level 信号，
> 而不是只靠报告写得像有依据。
> 本轮只做零付费实现；G1 尚未运行。

## 1. 已实现

### `utils/claim_support.py`

新增确定性 claim-support 审计：

- 读取 `final_recommendation.citation_sources` 中 decision-bearing 字段：
  - `recommendation`
  - `winner_rationale`
  - winner 的 `option=<winner>/rationale|key_strength|constraint_fit_reason`
- 按 source_type/provenance 分类：
  - `primary`：official_doc
  - `independent`：arxiv_paper
  - `community`：stackoverflow/reddit/community
  - `secondary`：其他 web/blog/github 等
- 按 canonical URL 去重；
- 产出：
  - `decisive_source_counts`
  - `distinct_sources`
  - `claim_support_flags`
- 典型 flags：
  - `recommended_no_primary`
  - `recommended_single_source`
  - `recommended_community_only`
  - `recommended_uncited`
  - `winner_rationale_uncited`
  - `conditional_no_primary`
  - `conditional_uncited`

### 接入 quality signals

- `conclusion_synthesizer` 写入 `claim_support_flags` / counts；
- `report_generator` 同样写入；
- batch_health 记录 `report_claim_support:*`（warn，不直接 invalid）。

### 接入 self-review

- self-review 输入新增 **Decisive Claim Support** 段：
  - 决定性来源数、primary/independent/secondary/community 计数；
  - flags；
  - 前 12 个来源的 class/type/title/url。
- 原有 check 1 已要求“单一 vendor/secondary/community 不能支撑决定性排名”；
  现在 reviewer 有确定性来源清单，不再只靠读正文猜。
- trigger skip 只在出现 `recommended_*` claim-support flag 时被强制覆盖；
  `conditional_no_primary` 不被强制 review，因为可能是诚实证据缺口。

## 2. 对最终 200 snapshot 的只读扫描

| 项 | 结果 |
|---|---:|
| recommended | 6 |
| conditional | 149 |
| insufficient_evidence | 45 |
| `recommended_*` flags | 0 |
| `conditional_no_primary` | 8 |

解释：

- 现有 final 200 的 6 个 recommended 都有 primary source，所以没有触发推荐级告警；
- 8 个 conditional 无 primary，属于先前已审阅的证据缺口型条件结论；
- 这轮不会改写已有结论，只让下一批 review 更可核。

## 3. 测试

- 新增 `tests/test_claim_support.py`：
  - recommended + official → 无 primary flag；
  - recommended + 单一次级来源 → no_primary/single_source；
  - 同 URL 只算一个决定性来源；
  - conditional no primary 仅诊断。
- self-review trigger 兼容旧的低风险 skip 测试。
- 全量测试结果见本轮执行记录。

## 4. 未做/边界

- 没有自动把 recommended 降级为 conditional：
  - 这属于“内容改写”，应由 self-review/模型判断，而不是确定性规则强行改结论；
- 没有生成完整 claim–sentence 映射（目前是 decision-field 级）；
- 没有新增“claim ledger”展示给用户；
- 没有跑 G1，也没有跑 200。

## 5. 下一步（G1，需批准）

Phase C 零付费实现完成后，用 G1 验证 self-review 是否能利用 claim support：

- 样本：20 expanded + 6 independent（26 例）；
- 预算估计约 1.6M tokens，上限 2.0M；
- 指标：
  - C2 partial 数量；
  - recommended/conditional 的 claim-support flags 与实际内容；
  - C4、contract invalid；
  - tokens；
- 不跑最终 200。

当前没有付费任务在跑。
