# 小样本验证结果：R7/R9 + 内容规则（2026-11-02）

> 目的：在**不重开正式 200** 的前提下，用 6 例小样本验证（a）R7/R9 零成本改动，
> （b）G1 暴露的残留内容缺陷的 prompt/自审/渲染修复。
> 结果只作方向性判断，不替代正式 200 指标；与冻结基线的逐例对照不是受控实验。

## 1. 案例选择与运行身份

- 案例（6 例，`.scratch/cases/cases_validation_small_20261102.json`，sha256 `08bf4f0c…`）：
  - **F200-070**：Elasticsearch vs OpenSearch（冻结时 official 0 页；验证 R7a 映射 + R7b guard）
  - **F200-176 / F200-082**：冻结 200 中证据省略最多（32,412 / 32,216 字符；验证 R9）
  - **F200-190**：G1 补充中 C3 partial（gap 准确性；验证新规则）
  - **F200-041**：G1 中 C2 partial（比较模式不对称；验证新规则）
  - **F200-165**：生命周期/模态残留（验证既有规则表现）
- 运行目录：`.scratch/cases/runs/validation-small-20261102/`
- 代码：git `db1747d` + 未提交的源文件改动（`dirty=True`，8 个源文件：内容规则 28–30、自审检查、
  渲染器 remainder/hedge、confidence 括号对齐）；**仲裁规则泄漏修复在本次运行之后**。
- 硬预算上限 520,000；concurrency 2；结果 **6/6 完成，474,496 tokens**；
  单例 p50 79,647；wall p50 246s / p95 365s。
- 健康：0 ok / 6 warn（均为 source_concentration、1 例 official 身份未验证、claim-support 告警），
  无 invalid。

## 2. 修复点验证（确定性信号）

### R7a — Elasticsearch 官方映射

| 指标 | 冻结 final-200 | 本次验证 |
|---|---|---:|
| F200-070 official body 页数 | 0 | **1** |
| official 通道 | 4 条结果全无正文（elastic.co 超时） | `www.elastic.co/docs` 抓取成功、has_body=true（2,302 字符） |

→ 映射改到 docs 深路径后，official 通道拿到了正文；其余 3 条（opensearch llms.txt 等）仍无正文，
符合"外部限制为主"的预期。评审确认：该正文被引用 3 次，报告的 ES/OpenSearch 决定性比较
仍以厂商迁移清单 + 第三方博客 + Elastic 自家博客为主，报告把证据可用性分支披露了两次、
排序降级为假设，**没有把 1 页官方正文当作决定性证据**（R7a 目标达成，且无 overclaim）。
Nit：同一文章的 CN/EN 两个 URL 被计为 2 个来源（报告有披露）。

### R9 — 证据包窗口/加权

| case | visible | omitted | stored 截断源 | full_included |
|---|---:|---:|---:|---|
| F200-041 | 22,519 | 27,442 | 4 | False |
| F200-070 | 14,023 | 0 | 0 | True |
| F200-082 | 22,198 | 32,323 | 4 | False |
| F200-165 | 23,127 | 0 | 1 | True |
| F200-176 | 22,488 | 34,511 | 4 | False |
| F200-190 | 21,590 | 25,561 | 3 | False |

→ 预算仍为 24k/例。评审确认两个最大省略 case 的**决定性事实都留在报告里**：
F200-176 的成本（MAR $5/conn 起、约 $2.50/M 行）、限制（自托管负担、S3 IAM-role OSS 限制）、
生命周期（2026 dbt merger 未确认、Core→Cloud 2026-08-18）；F200-082 的 Cilium 未测试清单/
enforcement-off 窗口、Calico CRD 迁移窗口、无 EOL 声明。R9 方向在报告侧成立。
残余：compact input 仍有 34.5k 字符省略（预算不变，属预期）；评审指出的 `[1]/[13]` 序号泄漏
与仲裁规则泄漏见 §4（均已修）。

### R7b — guard 动作

| case | decision | guard action |
|---|---|---|
| F200-041 | conditional | 无 |
| F200-070 | conditional | `conditional_top_option_strength_caveat`（新措辞：缺独立非厂商对照） |
| F200-082 | conditional | `conditional_top_option_strength_caveat` |
| F200-165 | conditional | `conditional_top_option_strength_caveat` |
| F200-176 | conditional | 无 |
| F200-190 | conditional | 无 |

→ F200-070 的 secondary-dominant 告警被新措辞 caveat 正确吸收（评审确认无 overclaim）；
本次 6 例**没有触发** `conditional_no_primary`，新增的 no-primary caveat 未被本样本覆盖，
留待下一次运行验证。

### 确定性报告卫生（6/6）

| 检查 | 结果 |
|---|---:|
| 未解析引用标记 | 0 |
| 自审注记泄漏 | 0 |
| 模板计数句 | 0 |
| 置信度 label/正文矛盾 | 0 |
| 参考来源重复（参考段内） | 0 |
| 裸 deep-doc 标签 | 0 |
| 决策摘要括号失衡 | 0 |
| 内部规则号泄漏 | 1（F200-082，见 §4，已修） |
| 裸来源序号 [N] | 1 例（F200-176，见 §4，已修） |
| 字面 `\n` 转义 | 1 例（F200-165，见 §4，已修） |

## 3. 内容评审（C1–C4，6 例）

| case | C1 | C2 | C3 | C4 | usable | DG | 旧 DG | 结论 |
|---|---|---|---:|---|---|---|---|---|
| F200-070 | met | met | met | 0 | ✓ | **✓** | ✓ | R7a 生效；证据可用性分支披露、无 overclaim |
| F200-176 | met | met | met | 0 | ✓ | **✓** | ✓ | R9 报告侧事实完整 |
| F200-082 | met | met | met | 0 | ✓ | **✓** | ✓ | R9 事实完整；仲裁规则泄漏（已修） |
| F200-165 | met | met | met | 0 | ✓ | **✓** | ✓ | 生命周期已真正纳入排序/条件/分支；无模态强化 |
| F200-190 | met | met | **partial** | 0 | ✓ | **✗** | ✓ | gap 准确性只修一半：import 缺口已修，许可缺口仍与所引正文矛盾；台账仍有已排除来源计数 |
| F200-041 | met | **partial** | met | 0 | ✓ | **✗** | ✗ | 比较仍不对称：把 NestJS 托管 Mau 对 ASP.NET 手工自托管，并称找不到 ASP.NET 托管方案，与所引 Microsoft 正文（Azure App Service）矛盾 |

- **合计：usable 6/6、DG 4/6、C4=0**；与冻结基线同 6 例对照：旧 DG 5/6 → 新 4/6
  （F200-190 本轮 C3 partial 为新发现；F200-041 仍 C2 partial；其余 4 例保持 DG）。
- 非受控对照，只作方向性判断；6 例不构成正式指标。
- **R7/R9 改动本身未引起新的 C4/usable 退化**；190/041 的 gap 与比较缺陷是内容规则只部分生效，
  不是 R7/R9 引入。


## 4. 本次新发现并已修复的缺陷（运行后修复，未参与本次运行）

1. **F200-082 仲裁推理泄漏内部规则号**：报告的争议裁决段原样渲染仲裁模型 reasoning，
   其中出现 "so rule 1 does not apply… (rule 2)"。运行后已修：
   - 仲裁 prompt 增加 "NEVER mention rule numbers…"；
   - 渲染层新增 `sanitize_arbitration_text`（把 `rule N` 替换为中性表述）作为兜底；
   - 三个渲染器（what_why_how / comparison_matrix / evidence_first）全部接入。
2. **F200-176 证据摘要泄漏裸来源序号**："[1] 与 [13] 是同一 Airbyte 对比页" 属 registry 内部编号。
   已修：合成 prompt 规则 31（禁止在正文写 [N] 序号）+ 自审检查项 + 渲染层
   `_resolve_single_bracket_numbers` 兜底（把可解析的 [N] 转成 [Source: title]）。
3. **F200-165 字面 `\n` 转义**：建议段出现 15 处字面 "\\n" 而非换行。已修：
   `finalize_report_text` 统一反转义 `\\n`/`\\r\\n` 并折叠多余空行。
4. 以上修复新增 5 项测试（仲裁 3、裸序号 2-3、字面转义 2，合计 8 项断言组）；全量测试 **854 passed**。

## 5. 结论与边界

- **R7a 有效**：F200-070 official 正文 0→1 页，映射改动生效且未 overclaim。
- **R9 报告侧成立**：两个最大省略 case 的决定性事实（成本/限制/生命周期）均留在报告可见内容中；
  预算未变。残余的 34.5k 省略属预算内预期。
- **R7b 部分覆盖**：strength caveat 新措辞在 F200-070 正确吸收告警；
  `conditional_no_primary` 新 caveat 本次未触发，仍待验证。
- **内容规则部分生效**：生命周期（F200-165）已真正纳入排序/条件/分支；
  gap 准确性只修一半（F200-190 import 修好、许可未修）；比较对称规则被声明但模型仍找不到
  ASP.NET 托管对照（F200-041 C2 partial）。两者与旧基线同级，不是回归。
- **新发现 3 个展示/内部元数据缺陷（仲裁规则号、裸来源序号、字面 \n）已运行后修复**，
  需下一次运行验证。
- 6 例不是正式指标；不改变冻结 200 的正式结果，也不迁移任何指标。
- 正式 200 按用户决定暂不重开；若后续开跑，建议把 F200-190/F200-041 的 gap/对称问题
  再做一轮 prompt/自审增强（或列为已知限制），并把本轮运行后的 3 个展示修复纳入发布说明。
