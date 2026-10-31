# Phase C 12 例分层 G1 结果（2026-10-30）

> 只跑 12 例分层开发集，未跑 200。

## 1. 样本选择

从 26 例 G1 开发集中按 category 各取 1 个，另保证覆盖原失败/边界案例：

- F200-001 Frontend
- F200-021 Backend
- F200-049 Database
- F200-076 Infra
- F200-104 CI/CD
- F200-117 Messaging
- F200-136 Observability
- F200-155 AI/ML
- F200-158 Security
- F200-172 Data
- F200-183 Python
- F200-198 Containers

12 个 category 全覆盖；包含 F200-117（winner-owned 来源）和
F200-076（同厂商 EN/zh 双 URL）两个目标 case。

## 2. 运行结果

| 项 | 结果 |
|---|---:|
| 完成 | 12/12 |
| tokens | **727,750** |
| health | 10 ok / 2 warn / 0 invalid |
| official 正文页 | 44 |
| 预算 | 估计 0.75M；上限 1.0M，未超 |

## 3. 内容评审

| 指标 | 结果 |
|---|---:|
| usable | **12/12** |
| decision-grade | **10/12** |
| C4 | **0/12** |
| C2 partial | 2/12 |

### 目标 case

- F200-117：由 `recommended` 变为 `conditional`，DG；
- F200-076：改为 insufficient hold，DG；
- 两个目标缺陷在本次生成中未复现。

### 新的非 DG（相对 26 例 retry 子集）

- F200-104（Buildkite vs CircleCI）：conditional，但 #1 Buildkite 的决定性比较
  几乎全部来自 Buildkite 自己的对比页，CircleCI 官方正文仅导航级；
  无 winner 外的独立支撑。
- F200-158（Keycloak vs Auth0）：默认 Auth0 分支的成本/耗时数字来自
  Skycloak/Authgear/Logto 等竞品或托管商博客，且为单来源；
  官方正文只有 430/510 字符导航级。

## 4. 与 26 例 retry 的对比

同一 12 例在 26 例 G1 retry 中的结果：

- usable 12/12
- DG **10/12**（F200-076、F200-117 非 DG）

本次 12 例：

- usable 12/12
- DG **10/12**（F200-104、F200-158 非 DG）

结论：

- 目标缺陷 **F200-076 / F200-117 已修复**；
- 但整体 DG **没有净提升**：修复了 2 个旧缺口，又出现 2 个新的 C2 partial；
- Phase C 仍未闭环。

## 5. 根因判断

claim-support 当前只对 `recommended` 检查 winner-owned 来源占比：

- F200-117 修复；
- 但 F200-104/158 是 **conditional 默认分支**，其排序仍可能被厂商/托管商
  单侧材料主导，而 `conditional_top_option_owner_dominates` 尚未实现；
- 另外，官方正文只有导航级时，`primary` 计数仍可能高估支撑。

## 6. 下一步（零付费）

1. 扩展 claim-support 到 conditional 的 top-ranked option：
   - 检测默认分支是否由该 option 自有来源主导；
   - 检测官方来源是否有实际正文（不是 nav）；
2. self-review 增加对应约束；
3. 再决定是否做第二次 12 例验证；
4. 不跑 200。

当前没有付费任务在跑。

## 7. 后续零付费实现（已完成）

- claim-support 增加：
  - conditional top-ranked option 的 `top_option_owner_dominates`；
  - `conditional_top_option_secondary_dominant`；
  - official binding 的 `has_body`（导航页不算 primary）；
- self-review 增加对应约束，且这些 flags 会强制 review；
- 只读扫描 12 例旧 snapshot：
  - F200-104 命中 `conditional_top_option_owner_dominates`；
  - F200-158 命中 `conditional_top_option_secondary_dominant`；
  - F200-117 命中 owner-dominates（已为 conditional）；
- 全量测试状态见提交记录。

## 8. 下一步

需要对同一 12 例做第二次分层 G1（约 0.73M tokens）确认这些 flag 是否真正让
self-review 改写默认分支；通过后再判断 Phase C 是否闭环。不跑 200。
