# R7/R9 零成本实施记录（2026-11-02）

> 依据 `R7_R9_EXPLORATION_20261102.md` 的结论，按用户指令先实施零成本项；
> 不改变证据预算总额、不新增检索调用、不改投递口径。
> 机器可读测量：`.scratch/cases/runs/final-200-20261031b/r9_offline_measurement_20261102.json`。

## 1. 实施内容

### R9-A 决定性锚点窗口（`utils/candidate_identity.py::_excerpt_spans`）

证据包超出预算时，原实现按"候选名窗口 + 附近限定词 + 头/尾各一半"选取；
中间段的关键事实（许可、生命周期、限制、成本、回滚等）可能被整段省略。
新增 `_DECISION_KEYWORDS`（约 55 个中英决策锚点）作为第二优先级窗口，并改为
**优先级顺序 + 合并去重的预算占用**：先放候选/子问题窗口与 qualifier，再放决策锚点，
最后才用剩余空间放头/尾。总预算不变。

### R9-B 按来源重要性的预算分配（`_evidence_limits` + `_source_budget_weight`）

原实现把剩余预算等分给大来源。现按来源信号加权分配（同一总预算内）：
`disputed +0.35`、`official_doc +0.20`、`body_identity_verified=True +0.15`、
community −0.10，权重夹在 0.6–1.75。小来源仍完整保留；不新增任何 token 预算。

开关：`shared_evidence_package(..., prioritize=, decision_windows=)`；
默认 True，测试可切回 legacy 行为做 A/B。

### R7a Elasticsearch 官方映射（`retrievers/official.py`）

`elasticsearch` 映射从 `https://elastic.co`（站点根，final-200 中 3 例 timeout）
改为 `https://www.elastic.co/docs`（官方 docs 深路径）。仍由抓取准入/身份校验决定
是否成为证据，不保证正文可取。

### R7b 无一手来源的条件结论 caveat（`utils/decision_guard.py`）

原 guard 只处理 recommended→conditional 与 owner/secondary dominant 的 conditional；
`conditional_no_primary`（7 例）只作为诊断。新增确定性 caveat：
条件结论若没有任何 primary（官方/独立）来源支撑，追加
"证据强度校准：该条件结论没有任何一手（官方或独立）来源支撑，属于证据缺口型判断…"，
动作名 `conditional_no_primary_caveat`，幂等。不改变排序或结论内容。

## 2. 离线测量（200 份冻结 snapshot，同一 24,000 字符预算）

| 指标 | legacy（改动前行为） | new（改动后） |
|---|---:|---:|
| 省略字符总数 | 2,054,906 | 1,796,238（−12.6%） |
| 决策锚点命中（可见文本内） | 15,320 | 17,172（**+12.1%**） |
| 可见字符总数 | 3,926,738 | 4,212,293（更充分利用预算） |
| 单例可见字符上限 | — | 23,991 ≤ 24,000 |
| 决策锚点提升的 case | — | **134/200** |
| 决策锚点略降的 case | — | 6/200（多为本身内容短、差异在噪声内） |
| 省略字符增加的 case | — | 15/200 |

> 第二轮（G1.5 验证后）把锚点列表按"具体决策事实优先"重排（licence/价格/生命周期/
> managed/hosted/托管 等排在 however/but 等通用限定词之前），并补充托管/许可类锚点；
> 上表为最终口径（重排后重测）。

结论：同样预算下，决定性内容（许可/限制/生命周期/成本等）在可见证据中的覆盖提高约 13%，
总预算不增加；代价是可见字符更贴近预算上限（约 +7% 证据 token 利用率，折合每例约 +0.5k tokens/次调用，
相对整单成本属噪声级）。

## 3. 测试

- 新增 `tests/test_r7_r9_improvements_20261102.py`（12 项）：加权预算不超总额、小来源完整、
  决策锚点在中段被保留、legacy 开关可回退、全量包不变、Elastic 映射、no-primary caveat 与幂等。
- 相关既有测试（evidence inputs / decision guard / claim support）全过。
- 全量测试：见提交时结果（本次运行中）。

## 4. 未做/待验证（需真实运行）

- **R7a 映射效果**、**R7b caveat 措辞在真实报告中的表现**、**R9 证据包变化对
  C2/C3 判定的真实影响**：均需下一次真实运行（G1 补跑或未来正式 200）验证；
  本轮 3 例台账补跑是在这些改动**之前**启动的（代码 `1b6a3e7`），不覆盖本记录改动。
- **R9 升预算（24k→30/32k）**：按探索结论留到正式 200 预算审批时决定，本轮未改。
- **R7b 检索侧独立来源配额**：需要 Tavily/时间成本，未实施。
