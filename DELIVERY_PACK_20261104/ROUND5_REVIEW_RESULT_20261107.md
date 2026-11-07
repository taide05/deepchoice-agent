# 第 5 轮（最终）第三层独立抽检结果（2026-11-07）

> 执行者：独立第三层 AI 审查会话（DSH，只读）。性质：**AI 辅助抽检**，非盲审、**不等同真人签字/全量验收**。
> 审查对象：最终版 200 例（`final-200-finalcode-20261106`）+ 修复批 provenance + 冻结 v3 + 最终报告。
> 本文件是本次审查唯一写入的项目文件；其余过程材料仅写 `.scratch/layer3_round5/`（草稿区）。
> 全程未联网、未启动任何模型调用批次/研究请求、未运行测试、未修改任何既有项目文件、未 git commit。

## 0. 结论速览（先给判定）

| 字段 | 值 | 简要依据 |
|---|---|---|
| **抽检验证** | **不通过** | 修复项、样本项通过；文档/记录项存在 blocker（见 §6） |
| repair_verified | **true** | 11/11 SHA 一致；复评 10 例中 9 例 C4=0，仅 F200-174 C4=1（已披露） |
| c2_records_ok | **false** | 最终指标快照早于独立层最后 4 例记录；修复集 C2 取内部层无书面裁决规则；F200-112 记录 notes/布尔不一致 |
| doc_sync_ok | **false** | 42,400,000 预算上限无工作区批准记录；FINAL:38 "方案 A：带披露定稿" 与校准记录不符；FINAL:28 C4 类型标注与源记录不一致 |
| sample_pass | **true** | 新抽 10 例：C4=0（10/10）、usable 10/10、C1/C3 10/10、DG 8/10；未发现新 C4 |
| can_mark_final | **false** | c2_records_ok / doc_sync_ok 未通过；且 AI 辅助抽检不能替代真人签字 |

**明确声明：本轮为 AI 辅助抽检，不等同真人签字/全量验收；样本不可外推全量 200；全量 200 中未被抽检案例的残余风险已由报告披露。即使本项通过也只支持"抽检验证通过"，不构成本项目的"最终验收通过"标记。**

---

## 1. 方法与证据边界

- 独立核对，不采信"项目方声称"：所有数字回到产物 JSON / 报告原文 / git 对象重算。
- 抽样方法（可复现）：排除口令给定 74 个 ID（本审查核实：74 个唯一且均为合法 F200 ID）后，池 = F200-001..200 的其余 **126** 例；用 Python `random.Random(2026110701).sample(sorted(pool), 10)` 抽取 **10 例**：
  `F200-030, F200-031, F200-045, F200-059, F200-062, F200-071, F200-086, F200-127, F200-139, F200-190`（均为 `origin=baseline161` 主批产物）。
- 修复验证 10 例 = 4 例 fix4last（029/124/174/192）+ 6 例 fix39（002/022/048/092/145/200）；F200-138 按口令只做 SHA 核对（不计入 10 例复评）。
- 阅读材料：`review_ready/<case>.compact.md` + `<case>.review.txt`（评审用去导航全报告）+ `report.md`（行号引用以此为准）；另有内部/独立两层评审 JSON、校准/裁决 JSON、provenance JSON、冻结 manifest、git 对象。
- 受审查约束未做（因此不能作为独立证据）：未重跑 `pytest`（"902 tests passed"为原记录，未复跑）；未重跑任何生成批次；未核对模型原始响应（只核对产物）。

---

## 2. A. 修复验证

### 2.1 SHA-256 核对（11/11 一致）

对比 `修复批/<case>/report.md` 与主运行目录 `final-200-finalcode-20261106/<case>/report.md`：

| 案例 | 修复批 | SHA-256（主目录=修复批） | 结果 |
|---|---|---|---|
| F200-029 | final-200-fix4last-20261107 | `571a5a826cce10a757a568c7c0fa483a9cfa370a5574ed42afd3a856a9d9bbde` | MATCH |
| F200-124 | final-200-fix4last-20261107 | `0413445cf8afd621222589aaad051cb79c1fad0c6555ec5d37bc049d3a325c51` | MATCH |
| F200-174 | final-200-fix4last-20261107 | `11cc3b5d4413c8818ada559b199be32fc875451bfc67b81cd81647b4a211a83a` | MATCH |
| F200-192 | final-200-fix4last-20261107 | `5c1909bb3fa7a3102eaa618448f251463deebf21607997d69693336977ad216f` | MATCH |
| F200-002 | final-200-fix39-20261106 | `ffbf28f3b931aec7f898003cec5c9028eb5a8f557b8d6208f31fc1585b2f7ee4` | MATCH |
| F200-022 | final-200-fix39-20261106 | `a90e409b8502a4f2005ad2218ab276c669e2d862b8ab1fa3f68994ace073de41` | MATCH |
| F200-048 | final-200-fix39-20261106 | `c36bc334474a17a4f5a2eb4eb9ed67b32ac6e1d87a47a3b56480e967b8b93ce6` | MATCH |
| F200-092 | final-200-fix39-20261106 | `a4f4f149e17cd70ca41a039ac195d292d0bd43fd00f3a5f726030cf66396b643` | MATCH |
| F200-145 | final-200-fix39-20261106 | `598adeb548ef8b3859572de4b449c111a0340ba6d75374e71efc76d4604219ba` | MATCH |
| F200-200 | final-200-fix39-20261106 | `66e464f3f83616776037e426c59d1bd0b7aa3796f23ba63be35eff7713cd11dd` | MATCH |
| **F200-138** | final-200-invalid-rerun138-20261106 | `2adfd12dc46c16ca883eee101c032f909bd0eeb3f64ed0ee4d3bd9dcfef9e099` | MATCH |

补充合并完整性核对：39 例 fix39 报告中 34 例与主目录逐字节一致，其余 5 例正是随后被替代的重跑案例（4 例 fix4last + F200-138 invalid 重跑），且这 5 例主目录版本与其最新重跑批逐字节一致。**合并链 fix39 → 138 重跑 → fix4last 完整、无未合并残留。**

### 2.2 逐例复评 JSON（10 例，v1.2.7）

```json
{"case_id":"F200-029","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L81门f1∧f2(+f3);L96反转同门;L64性能仅削弱默认=C4未见"}
{"case_id":"F200-124","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L113 G=(a)∧(b)∧(c)统一门与反转;L103暂缓+PoC=C4未见"}
{"case_id":"F200-174","C1":true,"C2":false,"C3":true,"C4":1,"usable":false,"decision_grade":false,"D1":4,"D2":4,"D3":3,"D4":4,"D5":4,"C2_failed_checks":[1],"C2_comparable":false,"notes":"C4:L94 B门(A1-A3全假)与L100回退仅护A1/A2冲突;C2#1:L90"}
{"case_id":"F200-192","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":4,"D5":4,"C2_failed_checks":[],"C2_comparable":true,"notes":"L87互斥谓词;L95翻转同门=C4未见;L124迁移对比仅Pulumi侧"}
{"case_id":"F200-002","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L77命中即停;L79-83栈前提互斥;L87同前提反转=C4未见"}
{"case_id":"F200-022","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L68-72 B1/B2/B3互斥;L76同门反转=C4未见"}
{"case_id":"F200-048","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L79默认Hapi→否则Koa→留旧,重叠有优先级=C4未见"}
{"case_id":"F200-092","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":3,"D3":3,"D4":5,"D5":4,"C2_failed_checks":[],"C2_comparable":true,"notes":"L73-76按序互斥;L86反转自洽=C4未见;多处能力主张单源"}
{"case_id":"F200-145","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L102-106按序判定+同门反转=C4未见;L24官文支撑分支"}
{"case_id":"F200-200","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":4,"D4":5,"D5":4,"C2_failed_checks":[],"C2_comparable":true,"notes":"L79门G;L81-84分支优先;L88同门反转=C4未见"}
```

### 2.3 复评说明（含唯一预期异常 F200-174）

- **F200-174（C4=1，已披露，符合预期）**：`F200-174/report.md:94` 定义 B 套（Fivetran）仅当 A1、A2、A3 **全部不成立**；`:100` 的回退条件却只以“A 套运维不可行/Airbyte 支持不满足”即退回 B 套，仅对 A1/A2 加了护栏，**漏掉 A3 门控**。即“A3 已成立（已进入 A 套）时仍可回退 B 套”，翻转条件与分支门控不一致，v1.2.7 下 C4=1 成立。披露准确（见 §4.6）。
- 其余 9 例：分支/优先级/flip 门控已核对，未发现 v1.2.7 定义的 C4 类缺陷：
  - `F200-029:report.md:81/86/96` 统一判定谓词 f1∧f2(+f3) 与反转条件同谓词；`F200-124:report.md:113` 决策门槛 G 被各分支与反转共同引用（须重满足完整 G）；`F200-192:report.md:87/91/95` B1∧B2 与默认支互补、翻转同谓词，原“C=不选任何工具”分支已移除；`F200-002:report.md:77/79-83/87` 命中即停+栈前提互斥+同前提反转；`F200-022:report.md:68-72/76` B1/B2/B3 互斥+同门反转；`F200-048:report.md:79` 默认 Hapi→否则 Koa→双败留旧，重叠有优先级；`F200-092:report.md:73-76/86` 按序互斥+反转自洽；`F200-145:report.md:102-106` 按序判定+同门反转；`F200-200:report.md:79/81-84/88` 门禁 G+分支优先级+同门反转。
- 9 例 C2 判 true 理由（v1.2.7）：决定性维度缺口在报告中显式披露并转条件分支/PoC（无默认赢家）；174 C2=false 为“同一判定维度把托管 Fivetran 对自托管 Airbyte 混比”（C2#1，两层原记录一致）。

---

## 3. B. 新抽样（10 例）

### 3.1 抽样口径核对

- 口令排除清单：74 个 ID（逐项核对：74 个唯一、全部为 F200 合法 ID）；池 126 例；种子 `2026110701`；`random.sample` 取 10；全部为 `review_final_200.json` 中 `origin=baseline161`（即主批产物，非修复后新跑），与口令一致。
- 样本分布：可核（均为 2026-11-05/06 主批产出；health warn 属正常）。

### 3.2 逐例复评 JSON（10 例，v1.2.7）

```json
{"case_id":"F200-030","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":4,"C2_failed_checks":[],"C2_comparable":true,"notes":"L77单一判定式+换向同门;L10/L62现网前提已声明=C4未见"}
{"case_id":"F200-031","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L86按序规则+反转+可翻转默认=C4未见;审计双侧缺口已披露"}
{"case_id":"F200-045","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L77/L79按团队经验两分支;L83重选条件=C4未见"}
{"case_id":"F200-059","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L114-120默认/替代+托管对齐+翻转=C4未见;ScyllaDB审计缺口已披露"}
{"case_id":"F200-062","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L93三选一互斥+翻转=C4未见;hold+PoC,缺口已列"}
{"case_id":"F200-071","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":3,"C2_failed_checks":[],"C2_comparable":true,"notes":"L70 hold+PoC,缺口已列=C4未见;L19置信度文字与medium相抵(D5)"}
{"case_id":"F200-086","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":3,"D3":3,"D4":5,"D5":5,"C2_failed_checks":[],"C2_comparable":true,"notes":"L73-81默认A/B/C/D分支+反转=C4未见;L55共同前提压测"}
{"case_id":"F200-127","C1":true,"C2":true,"C3":true,"C4":0,"usable":true,"decision_grade":true,"D1":4,"D2":4,"D3":3,"D4":5,"D5":4,"C2_failed_checks":[],"C2_comparable":true,"notes":"L70-78三互斥分支+PoC闸门+反转=C4未见;审计双侧零正文"}
{"case_id":"F200-139","C1":true,"C2":false,"C3":true,"C4":0,"usable":true,"decision_grade":false,"D1":3,"D2":3,"D3":2,"D4":4,"D5":4,"C2_failed_checks":[1],"C2_comparable":false,"notes":"L72托管W&B对自托管MLflow异形态=C2#1;L30审计双侧无官文"}
{"case_id":"F200-190","C1":true,"C2":false,"C3":true,"C4":0,"usable":true,"decision_grade":false,"D1":4,"D2":4,"D3":2,"D4":4,"D5":4,"C2_failed_checks":[],"C2_comparable":false,"notes":"L104-110 A/B互斥+同门反转=C4未见;L124仅Pulumi侧对比=C2不可比"}
```

### 3.3 样本汇总

- **C4=1：0/10**（未发现新的关键错误；含原内部层曾标 C4 的 F200-190，复核其分支 A/B 已互斥且翻转同谓词，C4=0 与最终裁决一致）。
- usable 10/10；DG 8/10（F200-139/190 因 C2 不可比）。
- C2：8 true / 2 false（139 异形态混比；190 仅 Pumilo 侧对比、不可比）——此两例与最终记录 C2=false 一致。
- D1–D5 低分项：071 D5=3（置信度文字与 `CONF: medium` 相抵）；139 D3=2；190 D3=2（决定性对比仅单侧/厂商材料）。
- 口径提示：样本全部来自**主批产物**（非修复后新跑），其 C2=true 值沿用 v1.2.5 校准（与最终记录一致）；**样本数字不可外推全量 200**。

---

## 4. C. 文档与一致性核验（逐项：通过/不通过 + 依据）

### 4.1 指标一致性：**通过**

- `FINAL200_FINAL_RESULT_20261107.md:27-34` 宣称 C4=1/200（F200-174）、C2=true 182、usable 199、DG 182。
- 独立重算 `review_final_200.json` 的 `rows`（200 行）：C4=1 仅 F200-174（`rows` 中 `C4=true` 1 例）；C2=true **182**；usable **199**；DG **182**；C1/C3 全 true；公式自洽（C4 类目与布尔、usable=C1&&C4==0、DG=usable&&C2&&C3）**0 处违规**。与报告数字一致。
- 与 `FREEZE_MANIFEST_20261107.json:7-15`（c4=1/c2_true=182/usable=199/decision_grade=182）一致。
- 运行完整性：`gate_result.json:4-19`（summary_rows=200、complete=200、health_invalid=0、tokens_used=15,993,977、pass=true）；`batch_meta.json:43-49`（200/200、tokens 15,993,977）；`batch_health.json` 状态 ok 34 / warn 166 / invalid 0。

### 4.2 冻结 v3 哈希与 commit：**通过（附时点说明）**

- `FREEZE_MANIFEST_20261107.json:3-5`：`code_commit=da99f23`、`src_tree_sha256=a51a5bc4123f4b94d67f705dece9d569fd9e4e79d01e2db8aae62c779d06b00d`。
- 独立重算（与 `.scratch/cases/make_freeze_manifest_20261105.py` 相同算法：对 `src/**/*.py` 排序、以"相对路径 + 文件 SHA-256"聚合）：**重算值 = a51a5bc4…，与 manifest 完全一致**。
- git 核对：`git status --porcelain -- src/` 为空；`git log da99f23..HEAD -- src/` 为空；最后一次触及 `src/` 的提交 = `da99f23`（`git log -1 --format=%h HEAD -- src` = da99f23）。**说明**：当前 HEAD 为 `04b1d76`（da99f23 之后 3 个纯文档提交），冻结规则允许文档提交；代码树与 da99f23 相同（src tree 均为 `01e2065…`），因此"代码提交 da99f23"成立。
- 主批冻结合规：主批 `batch_meta.json:12-18` 记录 commit `7af8ffaa`、`source_dirty=false`；git 层 `src` 树 `7af8ffaa == 890591d == tag freeze-final200-20261105(98d8229)` = `7d4b97de…` → 主批 200 确实用冻结代码跑完，运行期无 src 改动。
- 题集未变：`cases_formal_200.json` SHA=`46728f20…`，与 v2/v3 manifest 一致。
- 未独立复跑 902 tests（审查约束禁止跑测试）；该数字只能作为原记录，不能提供独立证据。

### 4.3 修复批 provenance、预算、残余风险披露：**部分不通过**

- **通过项**：`FINAL200_FINAL_RESULT_20261107.md:3-5` 列出 fix39 / fix4last / 138 重跑及批次名、token；`:12-13` 分列 39 例修复（含 138 重跑）3,342,375 = 3,254,081+88,294、最后 4 例 347,938；`:34` 披露"161 例沿用 v1.2.5 残余风险"。`FREEZE_20261107.md:15` 明确"同案例重跑无替换"；`FIX39_PROVENANCE.json:3`、`FIX4LAST_PROVENANCE.json:3` 同。独立核对：`cases_fix39_20261106.json`/`cases_fix4_last_20261107.json`/`cases_invalid_rerun_138_20261106.json` 案例集与 provenance、主目录 200 个 case dir 完全一致（200 个唯一 ID = F200-001..200，无替换、无缺失）。
- **预算数字通过**：独立重算累计 = 22,738,695（夜间累计，可由 `NIGHT_RUN_STATUS_20261103.md:41-51`+fix4 313,330 逐项相加得到）+ 15,993,977 + 3,254,081 + 88,294 + 347,938 = **42,422,985**，与 `FINAL:14`、manifest:16 一致；对 42,400,000 的超支 = **22,985**（0.054%）。
- **不通过项（凭证缺口）**：工作区内**找不到 42,400,000 上限的批准记录**。可核的书面批准只有 42,000,000（`UNFREEZE_20261106.md:35` "上限提升至 42,000,000（用户批准追加 2M）"）与 42,200,000（`NIGHT_RUN_STATUS_20261103.md:101` "42,075,047 / 42,200,000（用户批准 42.2M）"；`SESSION_CHECKPOINT_20261107.md:18`）。全工作区检索 `42,400,000/42.4M/42400000` 仅命中最终轮文档本身（FINAL:14、manifest:16、口令:17 及其交付包副本）。因此"超 22,985（0.05%）"的**分母基准不可独立核验**：若按 42.2M 计超支为 222,985（0.53%），按 42.0M 计为 422,985（1.0%）。需用户确认 42.4M 批准（若为会话内口头批准，请补书面记录）或更正披露。

### 4.4 状态措辞（抽检前不得标记最终验收）：**通过**

- `FINAL200_FINAL_RESULT_20261107.md:36-41`：明确"第 5 轮抽检口令已生成"、"**抽检通过前不得标记'最终验收通过'**；通过后由用户决定发布"。
- `FREEZE_20261107.md:14` 规则 1：到第三层抽检结束前不改代码/prompt/口径/配置/题集。
- 全工作区检索"最终验收"：未发现任何把本候选写成"已通过最终验收"的表述（其余均为历史轮次"不得标记/暂缓"记录）。

### 4.5 旧批指标未混用、样本结论未外推：**通过（附交付包陈旧提示）**

- `FINAL200_FINAL_RESULT_20261107.md` 只引用最终批指标（15,993,977、C4/C2/usable/DG 校准后值）；旧批 tokens 仅作为累计付费的组成隐含在 22,738,695 中，未把旧批指标当作本轮指标；未把任何抽检样本结论外推为全量（`:34` 反而披露残余风险）。
- `AI_SPOT_CHECK_LAYER3_20261104.md:5` 明示"不能外推为全量 200 例通过率"；本轮表述沿用。
- **提示（不构成本项不通过）**：`DELIVERY_PACK_20261104/README.md:9-12`、`metrics.json`、`review_metrics.json`、`gate_result.json` 等仍是第 4 轮旧批次内容，且未标注"已被 FINAL200_FINAL_RESULT_20261107 取代"；新最终文档已复制进同一目录（与根目录 SHA 一致）。交付包如对外使用，建议先更新或明确 superseded 标记，避免旧批指标被误引。

### 4.6 F200-174 披露准确性：**通过（小瑕疵：类型标签）**

- 准确性：`FINAL:27-28` 明确列出 C4=1 为 F200-174，`:30-32` 的 usable 199/DG 182 已扣除该例；`FREEZE_MANIFEST_20261107.json:8-11` `c4_ids=["F200-174"]`。独立复核其报告 `report.md:94/100` 确有翻转门控不一致（见 §2.3），**披露真实、未掩盖**。
- 小瑕疵：`FINAL:28` 把 174 归为"未调和矛盾"，而 `review_calibration/fix39adj.json`（174 条目）分类为 `branch_ambiguity`，`review_internal/internal-fix4last.json:45` 与 `review_independent/independent-fix4last.json:45` 的 notes 明确为"翻转门不一致/回退漏 A3"（v1.2.7 对应"C4-翻转条件与分支门控不一致"）。建议类型标签与评审记录对齐，并在报告正文点明 174 的具体行号。

### 4.7 其他一致性发现（记录，不改文件）

- `FINAL:38` "用户已确认方案 A：带披露定稿"：与 `CALIBRATION_RESULT_20261106.md:41-43` 的方案编号不符（方案 A = 定向修复全部 39 例；"带披露定稿"是方案 C）。建议改为"用户已确认带披露定稿（方案 C）"或类似表述。
- `FINAL:21` "v1.2.6 两层复评 39/39" 对 fix39 成立（内部/独立各 39 份记录齐全）；但最后 4 例（fix4last）的"两层复评"存在时序问题（见 blocker B2）。

---

## 5. 汇总与一致率（分母写明）

### 5.1 SHA / 合并

- SHA：**11/11 一致**（4 fix4last + 6 fix39 + F200-138）。
- 39 例修复合并：34 例主目录=fix39；5 例被后续重跑替代并各自与其最新批次一致（4 fix4last + 138 重跑）→ **39/39 有可追溯的最新版本，无替换**。
- 200 例 case dir 与题集 ID 一致（200/200，无缺失/无替换）。

### 5.2 修复 10 例与两层/最终记录一致率（判定完全相同）

| 对比对象 | C1 | C2 | C3 | C4 | usable | DG |
|---|---|---|---|---|---|---|
| 内部层最新记录（n=10） | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| 独立层最新记录（n=10） | 10/10 | 9/10（差 F200-192） | 10/10 | 10/10 | 10/10 | 9/10（192） |
| 最终记录（n=10） | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |

- 唯一不一致：F200-192 独立层 C2=false（"迁移对比仅 Pulumi 侧材料，CDK 官文仅 cookie/导航"），内部层与最终记录 C2=true。按 v1.2.7 复核：报告已披露该缺口并转为条件分支/PoC（`report.md:87-95`），C2 判 true 可接受；但见 blocker B2（最终快照早于独立层记录）。
- **预期差异**：除 F200-174（已披露 C4=1）外，未发现新的 C4=1。

### 5.3 新抽 10 例与两层原记录/最终记录一致率

| 对比对象 | C1 | C2 | C3 | C4 | usable | DG |
|---|---|---|---|---|---|---|
| 内部层原记录（v1.2.4，n=10） | 10/10 | 2/10 | 10/10 | 9/10（190） | 9/10 | 2/10 |
| 独立层原记录（v1.2.4，n=10） | 10/10 | 2/10 | 10/10 | 10/10 | 10/10 | 2/10 |
| 最终记录（v1.2.5 校准，n=10） | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |

- **预期差异说明**：原两层 v1.2.4 严格口径把"决定性维度单边/缺量化"一律判 C2=false（口径漂移，已在 `CALIBRATION_RESULT_20261106.md:26-30` 披露）；v1.2.5/v1.2.7 明确"缺口披露+条件分支/PoC 可判可比"，因此 C2/DG 与最终记录 10/10 一致、与原严格层仅 2/10 一致，属**已披露的口径差异**，不作为新缺陷。F200-190 原内部层 C4=1（分支 A/B 谓词可同真）在 v1.2.5 二次裁决中清零（`review_calibrated_200.json` 中 190=C4 0），本轮复核其现报告 `report.md:104-110` 的 A/B 已互斥、翻转同门，与最终 C4=0 一致。
- 新样本 C4=1：**0/10**。

---

## 6. 结论字段与 Blockers

### 6.1 结论字段

```text
repair_verified = true
c2_records_ok   = false
doc_sync_ok     = false
sample_pass     = true
can_mark_final  = false
```

### 6.2 Blockers（文件:行号 + 类型）

**B1（文档/披露，中）预算上限 42,400,000 无批准凭证。**
`FINAL200_FINAL_RESULT_20261107.md:14`、`FREEZE_MANIFEST_20261107.json:16`、`ROUND5_SPOT_CHECK_PROMPT_20261107.md:17` 使用 42,400,000 作为上限；工作区可核批准仅为 42,000,000（`UNFREEZE_20261106.md:35`）与 42,200,000（`NIGHT_RUN_STATUS_20261103.md:101`；`SESSION_CHECKPOINT_20261107.md:18`）。按 42.2M 计超支为 222,985（0.53%），非 22,985（0.05%）。需补批准记录或更正"超支"口径；否则"如实披露"的分母不可核验。

**B2（记录/口径，中）最终 C2/DG 快照未覆盖独立层对最后 4 例的复评，且修复集 C2 取内部层无裁决规则。**
`review_final_200.json`（mtime 2026-11-07 11:56:06，见其:4-11 头部与 rows）早于 `review_independent/independent-fix4last.json`（mtime 11:59:12，F200-174:45、F200-192:67）；`internal-fix4last.json:67` 与 `independent-fix4last.json:67` 对 F200-192 给出相反 C2（true/false）。最终记录采用内部层 C2（F200-192 最终 C2=true，`review_final_200.json:2115-2123`；F200-174 C2=false 一致）。对全部 39 例修复集，最终 C2 = 内部层 C2（独立层在 051/075/112/192 与内部层不一致），该合并规则未在报告/冻结文档中写明；若按独立层，C2/DG 分别至多降至 178/178。需在最终报告披露"修复集 C2 裁决规则 + 4 例两层分歧结果"。

**B3（记录一致性，低-中）F200-112 内部层 C2 记录瑕疵。**
`review_internal/internal-fix39-03.json:105`：C2=true、`C2_failed_checks=[]`，但 notes 明写"L182'已声明旧方案自定义规则'非输入=C2局限"；`review_independent/independent-fix39-03.json:105` 同例 C2=false（failed_checks=[2]，未声明前提）；最终记录 `review_final_200.json:1235` 采用 C2=true。按 v1.2.7 C2 判据#2（不得把未声明现网前提作为默认排序依据）与 v1.2.3 记录要求，该记录应重评/裁决（影响全量 C2 最多 1 例）。

**B4（文档细节，低）**
(a) `FINAL200_FINAL_RESULT_20261107.md:38` "方案 A：带披露定稿"与 `CALIBRATION_RESULT_20261106.md:41-43` 方案编号不符（A=定向修复；C=带披露定稿）。
(b) `FINAL200_FINAL_RESULT_20261107.md:28` 把 F200-174 的 C4 类型归为"未调和矛盾"，与 `review_calibration/fix39adj.json`（branch_ambiguity）及 fix4last 两层 notes（翻转门控不一致）不一致；建议统一为"翻转条件与分支门控不一致"并给出 L94/L100 行号。
(c) 交付包 `DELIVERY_PACK_20261104/README.md:9-12` 及旧 `metrics.json/review_metrics.json/gate_result.json` 仍为第 4 轮旧批内容且未标 superseded（新最终文档已复制，根目录与交付包副本 SHA 一致）；对外发布前需更新或显式标注。

### 6.3 未构成 blocker 的说明

- 902 tests：受只读/不跑测试约束未复跑（不能作为独立证据，也不据此判失败）。
- 引用 gap / health warn / 缺量化数据：按 v1.2.7 不作为单独不可用依据；本轮未据此判 C4。
- 主批 `batch_meta.json` 记录 commit 7af8ffa 与文档"冻结代码 890591d"：已用 git src 树哈希证明二者 src 树完全相同（`7d4b97de…`），非不一致。

---

## 7. 声明

1. 本报告是**AI 辅助第三层抽检**，非盲审（已知项目方结论），**不等同真人签字**，也不构成本项目的最终验收决定。
2. **样本不可外推全量 200**：修复 10 例 + 新抽 10 例只支持"抽检验证"层面的判断；全量 200 中未被抽检案例仍沿用 v1.2.5 校准结论（默认无 C4），该残余风险已由最终报告披露，本轮未消除。
3. 即使抽检样本通过，也只支持"抽检验证通过"口径；**在文档/记录 blocker（B1–B3）未修正前，不得标记"最终验收通过"**。
4. 若项目方修正 B1–B3（并澄清 B4）后重新提供版本，应重新执行抽检（至少复核受影响的 F200-112/192 与预算披露项），不能沿用本轮结论。
5. 审查期间未修改任何既有项目文件；临时材料位于 `.scratch/layer3_round5/`。

---

### 附：本审查使用的关键命令/核对方式（可复现）

- SHA：PowerShell `Get-FileHash -Algorithm SHA256` 对比修复批与主目录 `report.md`（11 例，见 §2.1）。
- src_tree：Python 复刻 `make_freeze_manifest_20261105.py` 的 `tree_hash()`（排序 `src/**/*.py`，对 `relpath` + 文件 SHA-256 更新摘要）。
- git：`git rev-parse HEAD`、`git log -1 --format=%h HEAD -- src`、`git log da99f23..HEAD -- src`、`git status --porcelain -- src`、`git rev-parse {98d8229,890591d,7af8ffa}:src`。
- 指标重算：Python 读取 `review_final_200.json` rows，重算 C4/C2/usable/DG 并校验公式。
- 抽样：`random.Random(2026110701).sample(sorted(pool), 10)`（排除 74 ID 后池=126）。
