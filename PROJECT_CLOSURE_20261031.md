# 项目阶段收口（2026-10-31）

> 本文件关闭 Phase A/B/C，冻结最终 200 结果，列出后续 backlog。
> 未跑新的 200。

## 1. 冻结结论

### 最终 200（2026-10-30）

- 10 批 ×20 例，200/200 单位齐全；
- 替换 5 例（1 invalid + 4 引用问题）；
- tokens：**12,646,242**；
- wall p50 221.2s / p95 415.1s；
- 全量评审：**usable 200/200、DG 185/200（92.5%）、C4=0**；
- 状态：recommended 6 / conditional 149 / insufficient_evidence 45；
- **最终 200 保持冻结**，Phase A/B/C 后的代码改动没有回写重跑。

### Phase A

- 引用账本/标题别名/契约 flags/batch health/厂商对比标签；
- 当前代码 200 snapshot 重放：ledger 不一致 64→6（旧 snapshot 括号标题），
  used-not-in-body 5→0，raw marker 0；
- 全量测试通过。

### Phase B

- 官方证据获取改进：映射修正、GitHub raw README、版本路径 fallback、
  top-path 边界、gzip 解码；
- 26 例 G1：official 正文 86→96，usable 26/26、DG 25/26、C4=0；
- Phase B 闭环。

### Phase C

- claim-support：primary/independent/secondary/community/navigation 分类，
  winner-owned/secondary-dominated flags；
- structural decision guard：recommended→conditional/hold，
  conditional 默认分支降级为待验证假设；
- 12 例 guard 验证：**usable 12/12、DG 9/12、C4=0**；
- 剩余 3 例（F200-158/172/183）是真实证据缺口，不是决策规则可修的问题；
- **Phase C 结构性部分关闭**，不继续为 3 个缺口付费刷 DG。

## 2. 成本摘要

| 项目 | tokens |
|---|---:|
| 最终 200 | 12,646,242 |
| Phase B G1 | 1,581,480 |
| Phase C 验证（含 402 失败运行、重试、2 例、12 例两轮、guard） | 约 5.29M |

后续不再有 approved paid run。

## 3. 明确未做/后置 backlog

1. 报告过长：最终 200 中位数约 21.7k 字符；后续可做“决策摘要 + 证据附录”分离；
2. 官方覆盖残余：JS/导航站、403 反爬、ConnectError 等外部限制；
3. C2 证据缺口：F200-158/172/183 类，只能补检索或如实保留；
4. claim-support 目前是 decision-field 级，未到逐句 claim 级；
5. 旧 snapshot 的方括号标题 artifact 不修；
6. Phase A 的 B（registry canonical merge）与“噪声来源硬排除”仍未做；
7. 外部材料：默认不发布；对外口径需用户确认。

## 4. 当前状态

- 最终 200：冻结；
- Phase A/B/C：按上述定义关闭；
- 无付费任务；
- 无未提交代码改动（`learned_docs.json` 为运行时数据，不提交）；
- 全量测试最近结果：**789 passed**。

## 5. 后续若继续

只建议两类零付费工作：

- 报告形态/长度优化；
- 验证与文档整理。

任何新的正式 200 或大规模行为实验都需要新的明确批准与预算。
