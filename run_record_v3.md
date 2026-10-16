# 单例研究交付记录 v3（任务 8049500c）

> **验收结论更正（本文件初版称"四项交付标准全部达到"，该结论已撤回）**
>
> 撤回理由：初版把"链路跑通 + 引用不悬空 + 候选段落非空"当作内容达标，**放宽了标准 2 与标准 3 的实质要求**。据实复核后，本份报告**未通过**内容验收，两个已确认的共同问题如下。
>
> **问题 A — 来源/段落主语/候选的对应关系不成立。** 页面提到某候选 ≠ 该页全部内容都属于该候选：
> `Amazon OpenSearch Service` 段落引用的 Elastic 对比页正文讲的是 **Elastic 自家 Observability/Security 定价与 $24 起价**，被当作该候选的成本依据；`ClickHouse` 段落引用的 SelectDB 博客正文讲的是 **SelectDB 自身**；`UltraWarm $0.024/GB-月` 出自一篇**第三方博客**（cloudchipr），却被用作排名第 2 的定价杠杆。
>
> **问题 B — 已有正文的来源被显示为"没有资料"。** `Amazon Athena over S3` 段落写"本次检索未取得明确指向该候选的材料"，但报告**同一份**里 `Amazon Athena - Serverless Interactive Query Service` **有 1224 字节正文**、且**被 `[Source: …]` 引用**。这是**传递问题**，不是真的没资料。
>
> **问题 C — 生成结论超出现有证据。** 报告同时写着"**0 条 strong 链**"、"Serverless 候选**无归属材料**"、"OCU 计费**缺少公开证据、必须实测**"，却把 `Amazon OpenSearch Serverless` **排为 #1**；`UltraWarm $0.024/GB-月`、`Athena ¥41.20/TB` 等数值与适用条件未经核对即用于排序理由。
>
> 用户已就此开新的修复包，本节仅记录事实；**不手改原报告**。

## 一、运行身份与结果

| 项 | 值 |
|---|---|
| 生产代码冻结 | **`21d7162ac136d16193cfb39c74e20ad06d11bd26`**（`precodex/deepseek-adapter`；生产文件与运行中的 `f3c8bae` **逐文件哈希一致**，仅测试文件不同） |
| 服务 | PID **21756**，`127.0.0.1:8100`，实际导入 `D:\deepchoice-precodex\src\` |
| 健康检查 | `GET /health` → **200** `{"status":"ok"}` |
| 派发 | **13:15:55**，task `8049500c-bd39-44e4-81bb-a1fbbebac780` |
| 结束 | **约 13:20:24**，`status: complete`，`confidence: low` |
| **停止点** | **正常完成，未触发任何停止线** |
| 题目哈希 | `3556F735F32CC42F5E25E54023C40BF3E8F7DF828139F3F8C19C3E9D6FB8510B` |

## 二、实际用量

| 项 | 实测 | 上限 | 用尽 |
|---|---|---|---|
| LLM 实际请求 | **24** | 40 | 60% |
| Tavily 实际 POST | **5** | 24 | 21% |
| 研究墙钟 | **268.5 s** | 900 s | 30% |
| 拒绝 | LLM 0 / Tavily 0 | — | — |
| 报告 | **24 079 字节** | — | — |

## 三、原始产物（未手修）

| 文件 | SHA256 前缀 | 大小 |
|---|---|---|
| `outputs/8049500c-…/report.md` | `BCEA0DE371148B70` | 24 259 |
| `outputs/8049500c-…/research_snapshot.json` | `72B2D9C86CABC294` | 187 545 |
| `outputs/8049500c-…/run_limits_counts.json` | `C0645CD029F6D69D` | 351 |

## 四、逐项验收

### 标准 1 — 完整链路正常结束，报告可查询、可展示 → **通过**
链路完整跑通（9 节点），`status: complete`，无 `partial_failures`。经**真实端点**验证（`TestClient`）：
`/report` 200 且正文非空、`/annotated` 200 且含报告与引用注册表、`/export?format=md` 200、
`/export?format=pdf` 200 且为真 PDF。

### 标准 2 — 候选介绍有实质内容，回答选择条件、理由与关键取舍 → **不通过**
- **形式上**四个候选都有段落且非只有标题；`Winner: 无唯一胜者`，并给出四个条件化分支。
- **实质上不通过**：段落里呈现的"材料"其**主语并非该候选**（问题 A），而真正关于候选的来源（`Athena`，1224 字节正文）反被写成"没有资料"（问题 B）；因此**候选介绍的内容不是该候选的**，选择理由也**建立在未核对的数值与第三方博客之上**（问题 C）。
- 报告自陈 `confidence: low`、0 条 strong 链、缺少独立基准与官方定价页。

### 标准 3 — 引用与候选及具体论断相符；导航链接/泛化说明/资料缺口不冒充依据 → **不通过**
**机制性检查通过的**（仅说明"没有悬空引用"，不等于论断相符）：
- 被引的 7 个来源都有正文，**无一对无正文链接发引用**；无悬空引用。
- **导航链接未冒充依据**：4 处明确标注，且无正文来源未进引用注册表、标题上无引用锚点。

**不通过的实质问题**：
- **段落主语与候选不符**（问题 A）：Elastic 页面内容 ≠ `Amazon OpenSearch Service` 的成本依据；SelectDB 博客内容 ≠ `ClickHouse` 的依据；第三方博客的 UltraWarm 单价被当作排名理由。
- **已有正文被显示为无资料**（问题 B）：`Athena over S3` 报缺口，而其来源有 1224 字节正文且在正文被引用。
- **结论超出证据**（问题 C）：0 条 strong 链、首选候选无归属材料、其计费"缺少公开证据"，却仍排 #1 并给出具体数值型排序理由。
- **逐句支撑性**：`OpenSearch Serverless 免集群管理` 所引 `OpenSearch vs ClickStack` 的正文摘要为查询/文件格式支持，**未直接呈现该论断**。

### 标准 4 — 启动与演示可复现，已知限制如实记录 → **通过**
**启动（可复现）**：
```powershell
cd D:\deepchoice-precodex
D:\deepchoice-agent\.venv\Scripts\python.exe run_service.py
# 就绪判据：GET http://127.0.0.1:8100/health -> 200 {"status":"ok"}
# 派发：POST /research  -InFile run_payload_v3.json
# 取报告：GET /research/{task_id}/report（或 outputs/{task_id}/report.md）
# 展示：GET /research/{task_id}/annotated | /export?format=md | /export?format=pdf
```
启动时打印**实际导入源码路径**与**实际解析的状态路径**，五条路径任一条落在工作树外即拒绝启动（exit 3）。

**已知限制（如实）**：
1. 本报告 `confidence: low`；**0 条 strong 链**，关键对比多来自厂商博客，**缺少独立基准与官方定价页**。
2. 两个候选（OpenSearch Serverless、Athena over S3）**本轮无归属材料**，报告以缺口呈现而非填补。
3. 上述 1–2 条具体论断的**逐句支撑性未能核实**。
4. `/export?format=pdf` 中**引用锚点链接会丢失 href**（xhtml2pdf 丢弃 `inject_citations` 的内联 HTML）；此为**既有缺陷**（`8456f66` 引入，非本轮引入），**正文 URL 文本仍在**，md/annotated/report 不受影响。
5. `qwen-flash` 档位在本适配中指向 DeepSeek（`deepseek-v4-flash`），因此**不是**历史 Qwen 行为的复现；候选记为"48b32bd＋服务适配"。
6. 两条 `test_frontend_obs.py` 失败在**纯净 48b32bd 同样失败**，属既有问题，**未宣称全套通过**。
7. 一份通过**只证明该题可用**；稳定性与跨场景能力**未作判断**。

## 五、独立复核

- `f3c8bae` 的聚焦复核结论：**BLOCKING: no**。逐项 CONFIRMED：普通证据不再被误标、无正文来源仍被标注、链接可达（含四端点）、无路由把无正文来源作为可引用依据、全套 359 passed + 2 既有失败、范围仅 3 个文件、无新依赖。
- 复核提出的唯一非阻断项（误标回归测试未走 `_cited_source`）已在 `21d7162` 修正：新测试驱动**真实冲突构造**并断言普通来源的 `snippet` 存活。
- 更早一份针对 `f3c8bae` 的复核代理**运行 90 分钟后静默终止、未返回结论**，故另起时限复核；此事**如实记录**。

## 六、判断

**本份报告未通过内容验收。** 工程链路正常（标准 1、4 通过），但**标准 2、3 不通过**：候选段落的内容主语与候选不符、已有正文的来源被显示为无资料、排序结论超出证据（0 strong 链却排 #1 且给出未核对的具体数值理由）。

**原报告已保留、未手改**（`report.md` `BCEA0DE371148B70…`）。本次额度已消耗，**不自动补跑**；下一份真实验收另定授权。
