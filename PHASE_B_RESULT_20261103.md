# Phase B 定向验证结果（2026-11-03/04）

> 目的：验证 Phase A 的零成本修复（服务端抓取兜底、32k 证据预算、独立源配额）在真实管线中生效。
> 所有运行只读冻结题集，使用新代码；不改变冻结批产物。付费调用已获用户夜间授权（≤22M）。

## 1. 运行身份

| 项 | B1 | B2 |
|---|---|---|
| 案例 | 10 例（官方 0 页 5 + 高截断 2 + 来源集中 3） | 5 例（官方 0 页全部） |
| 时间 | 2026-11-03 23:34–23:57 | 2026-11-04 00:22–00:40 |
| 代码 | `12a0ed4` | `a8ed6fc`（含下方三个修复） |
| 配置 | `EVIDENCE_INPUT_BUDGET_CHARS=32000`、并发 2、timeout 1800 | 同上 |
| 完成 | 10/10 | 5/5 |
| tokens | **753,745**（上限 900k 内） | **350,770**（上限 500k 内） |
| 产物 | `.scratch/cases/runs/phase-b-targeted-20261103` | `.scratch/cases/runs/phase-b2-fetch-fallback-20261103` |

## 2. 关键发现：Tavily extract 兜底此前从未生效（已修复）

B1 的 10 例中 `tavily_extract` 页面数 = **0**。复查发现三个串联缺陷：

1. **端点 bug（根因）**：`post_with_failover` 把 Tavily 端点硬编码为 `/search`，`/extract` 调用实际被发到
   `/search`（payload 无 query）→ 4xx 静默返回空。修复：`post_with_failover(..., url=)`，
   `tavily_extract.py` 显式传 `TAVILY_EXTRACT_URL`（`35db3c9`，含回归测试）。
2. **provenance 未落字段**：fallback 结果带 `fetch_via="tavily_extract"`，但官方条目构造只拷贝
   `body_admission`，未拷贝 `fetch_via`。修复：条目补写 `fetch_via`（`eb28262`）。
3. **403 不触发兜底**：OpenSearch 官方页对本地 pinned fetch 返回 `http:403`，不在可重试标记内，兜底不尝试。
   修复：`http:403/429` 加入兜底触发（`a8ed6fc`）。

另修复：模型偶发输出 `[[Source: title]]` 双括号引用会被“截断引用”清洗规则碎成大量
`〔引用未解析：截断〕`（B2 F200-030 出现 60 处）；现在先修复双括号再生成 gap 标记（`eb28262`）。

## 3. 修复生效证据（B2 vs 冻结批，同案例）

| 案例 | 官方正文页 冻结→B2 | extract 页数 | 说明 |
|---|---:|---:|---|
| F200-030 Echo/Fiber | 0→3 | 0 | Echo 官方 `/docs` 本地与 Tavily 均不可达；gofiber + echo llms.txt 可用 |
| F200-070 ES/OpenSearch | 0→3 | 2 | elastic release-notes 经服务端 extract 取得 |
| F200-071 ES/OpenSearch | 0→3 | 2 | 同上 |
| F200-072 ES/OpenSearch | 0→3 | 1 | 同上 |
| F200-088 Envoy/HAProxy | 0→3 | 2 | docs.haproxy.org 与 envoy api 页经 extract 取得 |

- B2 全部 5 例官方正文页 = 3（冻结批为 0），证明兜底链路打通；
- 070/071/072 的 OpenSearch 页在 B2 时仍因 403 未触发兜底（B2 跑在 `a8ed6fc` 之前）；该修复已进 C/D；
- **残余限制**：echo.labstack.com 本地与 Tavily 服务端均不可达，Echo 侧仍无官方正文；诚实披露；
- 官方页面存储上限 8,000 字符，extract 来的大页（elastic release-notes 页面 92 万字符）只入 8,000，
  `stored_truncated=True` 会披露，但决定性引用可能落在截断区。

## 4. 32k 证据预算生效情况

| 运行 | full_included=True | 截断案例 omitted chars |
|---|---:|---|
| B1（10 例） | 5 | 12,052–26,912（5 例） |
| B2（5 例） | 3 | F200-071 7,001（其余 full） |

- 预算确实从 24k 提到 32k 并生效；但正文丰富的案例仍会截断（官方正文 + 社区正文总量超过 32k）；
- 单例 token 成本约 57k–108k（均值 ~75k），与冻结批同案例相比普遍 +5–15%，符合预估。

## 5. 健康度

- B1：ok 1/10，warn 9；原因主要是官方页 ConnectError/timeout、来源集中、claim-support 提示；
- B2：ok 1/5，warn 4；F200-030 的 60 个截断 marker 已定位为双括号引用问题（已修）；
- 无 invalid、无任务失败、无 provenance 缺失。

## 6. 结论与下一步

1. **零成本修复基本验证通过**：32k 预算、服务端抓取兜底、403 重试、provenance 字段均可用；
2. **仍存在的已知限制**（进入正式报告披露）：echo.labstack.com 双通道不可达、官方页存储 8k 截断、
   部分案例证据仍超 32k；
3. Phase B 累计 tokens：**1,104,515**（B1+B2），在 22M 预算内；
4. 下一步：Phase C pilot-30（完整性+健康度 gate）→ Phase D 正式 200。
