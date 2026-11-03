# 第三轮小样本验证结果（残留修复后，2026-11-03）

> 目的：验证第二轮验证暴露的 5 项残留修复（041 排名同模式、151 摘要级来源不当正文、
> 台账未计入用源、覆盖行缺 page 级失败、截断条目/口吻/差 1），3 例：F200-041 / F200-151 / F200-190。
> 非正式指标，仅作方向性判断；运行时间 2026-11-03 09:26–09:37（本地），审批上限 260,000 tokens。

## 1. 运行身份与成本

- 目录：`.scratch/cases/runs/validation-r3-20261102/`
- 案例：`.scratch/cases/cases_validation_r3_20261102.json`，sha256 `14984bc2…`
- git：`9b3ba8e` + 未提交源文件（第三轮残留修复，source_dirty=True）；concurrency 2；硬上限 260,000
- 结果：**3/3 完成、234,978 tokens**（上限内）；单例 p50 77,824；wall p50 271s / p95 461s
- 健康：0 ok / 3 warn：
  - F200-041：source_concentration（learn.microsoft.com:3）
  - F200-151：HF TGI 官方页 ConnectError ×3、**citation_gap_markers:50**、
    `report_ledger:availability_claim_with_collected_bodies`
  - F200-190：官方页身份未验证 ×1、citation_gap_markers:1、source_concentration、secondary_dominant

## 2. 定向修复验证

### F200-041 — 同模式排名（成功）

- 报告正文（方案排名 #1）现在明确写出：
  "部署侧同为对等比较：与 ASP.NET Core 的 Azure App Service 路径对应，NestJS 有官方托管平台 Mau，
  两者都提供托管与自托管两种模式，因此运维负担的差异取决于你们选哪种模式"；
  #2 也以条件分支呈现，不再声称"没有可比托管方案"。
- 全文 0 处 `正文未取回`、0 处 `[N]`、0 处规则号；0 个 citation gap；official 5 页。
- 评审：见 §3。

### F200-151 — 摘要级来源与覆盖行（部分验证）

- 外部抓取仍失败（HF TGI 三页 ConnectError、vLLM production-stack 无正文），报告仍偏薄（20,464 字符）；
  决策由 conditional 变为 **insufficient_evidence**（评审判断是否为诚实 hold）。
- **本轮暴露新缺陷（已运行后修复）**：
  1. **混合标记嵌套 gap**：模型写 `[Source: vLLM — Official Documentation [[4]]`，
     解析器把 `[[4` 吞进标题 → 标题 gap 内嵌数字 gap，最终 50 个嵌套 gap。
     修复：解析前拆分混合标记（`_split_mixed_citation_markers`）+ finalize 折叠嵌套 gap
     （`_collapse_nested_gaps`）+ 测试。
  2. **只有 page 级失败时覆盖行缺失**：本轮 `partial_failures` 为空、仅 HF 页面抓取失败，
     `derive_data_source_note` 早退导致**无数据覆盖行**。修复：page 级失败独立触发覆盖行，
     并列出失败类型（ConnectError/timeout 等）。
  3. 摘要缺口条目去掉引用标记后残留"标点+空格"（如"无 NestJS 对照， 的对手是"）→ 已修。
- 这些都是本轮运行后修复，**未参与本轮报告**；需下一次运行验证。

### F200-190 — licence/gap 回归检查（等待评审）

- 报告 16,738 字符、1 个 gap（VPC 社区帖，诚实社区证据）；guard `conditional_top_option_strength_caveat`；
  全文 0 处"材料中没有任何/没有任何来源"、0 处 `[N]`、0 处规则号。
- 评审：见 §3。

## 3. 内容评审（C1–C4，3 例）

| case | C1 | C2 | C3 | C4 | usable | DG | 冻结基线 DG | 本轮结论 |
|---|---|---|---:|---|---|---|---|---|
| F200-041 | met | **met** | met | 0 | ✓ | **✓** | ✗（C2 partial） | **同模式排名修复成立**：排名 #1/#2 都以托管（Mau / Azure App Service）+自托管两种模式对等比较，明确"运维负担差异取决于你们选哪种模式"；#2 的托管路径被纳入；5 个 official 正文全部作为已取得正文引用；不再声称 Microsoft 正文未取回 → **C2 改善为 met、DG 改善** |
| F200-190 | met | met | met | 0 | ✓ | **✓** | ✓ | licence/gap 修复保持：报告不再对许可做任何"缺失"断言；500 资源上限仍归因 Pulumi 厂商页并带可见范围说明；VPC 社区帖仍按"社区经验/非官方事实"处理；**台账新增"另有 5 个未计入本清单来源"披露**（本轮新渲染生效） |
| F200-151 | met | **partial** | met | 0 | ✓ | **✗** | ✓（但薄因外抓失败） | 诚实 hold：3/3 HF TGI 官方页无正文 → TGI 无官方正文，报告明确"证据不足"并给出最低证据清单；报价数字全部可在检索摘要中逐字核对，无编造。C2 被**证据记账问题**拖累：'实际引用了 3 个来源' 与实际 9 个不符、负载性能研究未列入参考来源、摘要级来源被称为"正文"、缺 page 级覆盖说明；89 个嵌套 `〔引用未解析：来源标题 …〔引用未解析：编号 N（截断）〕〕` 是混合标记解析缺陷（见 §2） |

- **合计：usable 3/3、DG 2/3、C4=0**；与冻结基线同 3 例（旧 DG 2/3：041 非 DG、190/151 DG）相比：
  **F200-041 由非 DG → DG（目标修复达成）**，190 保持 DG，151 因外部抓取 + 记账缺陷暂时非 DG。
- 非受控对照，仅作方向性判断。
- 151 的 C2 缺陷中，**嵌套 gap / 台账引用数 / 覆盖缺失**均源于本轮已定位的两个 bug
  （混合标记解析、覆盖行早退），已运行后修复；仅"摘要级来源被称为正文"主要靠 prompt/自审规则，
  需下一轮确认。

## 4. 结论与边界

- **F200-041 目标修复达成**：同模式排名 + 托管路径纳入 + 不再误称正文未取回 → C2 met、DG true。
- **F200-190 保持 DG**：licence/gap 修复未回归；新台账"未计入本清单"披露生效。
- **F200-151 非 DG 但 usable**：薄是外部抓取失败（HF TGI 3/3 无正文），hold 诚实；C2 由证据记账
  问题拖累。其中嵌套 gap（89 处）、"引用 3 个来源"（实际 9 个）、覆盖行缺失均已在运行后修复：
  - 混合字面+数字标记拆分（`_split_mixed_citation_markers`）→ 不再把 `[[N]]` 吞进标题；
  - finalize 折叠嵌套 gap（`_collapse_nested_gaps`）；
  - 覆盖行 page 级失败独立触发（即使渠道失败为空）；
  - 摘要缺口去标记后的标点清理；摘要级/正文规则（prompt 规则 33）。
  全量测试 **876 passed**。这些修复**未参与本轮报告**，需一次小样本（建议仅 F200-151，~85k tokens）
  确认后再定残留下一步。
- 3 例非正式指标；不改变冻结 200 结论；正式 200 按用户决定暂不重开。
