# Community 通道可靠性加强（2026-10-29）

> 针对独立 6 例里的 2/6 失败；通用基础设施修复，不按案例做特殊处理。

## 1. 失败与根因

独立 6 例：

- F200-001：`StackExchange per-case request budget exhausted`；
- F200-021：`TimeoutError()`。

根因：

1. **每 case 请求预算 6 太紧**：2 次搜索 + 3 次批量详情 = 5，任何一个重试就会耗尽预算；
   重试本身也计入真实请求，预算没有给瞬时失败留余量。
2. **TimeoutError 未纳入重试捕获**：resolver/请求层抛出 built-in `TimeoutError` 时，
   旧代码只捕 `RuntimeError`/httpx 异常，可能直接失败。
3. **source-level 没有第二次机会**：内部 3 次重试都失败后直接标 failed，
   没有在社区源层面再尝试一次。

## 2. 修复

- `MAX_CASE_REQUESTS`: 6 → **8**，给搜索+详情+两次瞬时重试留空间；
- `_community_client` / `_request_json` 捕获 `TimeoutError` 并纳入有界重试；
- `CommunitySearch` 的 evidence_pack 分支增加一次 source-level 重试（2s 后，
  仅对 RuntimeError/TimeoutError；不改变 no-results 语义）；
- 没有改动查询/选择/评分逻辑；没有加案例黑名单。

## 3. 复测

对原先失败的两例复跑（F200-001、F200-021）：

- 2/2 complete，131,342 tokens；
- community **2/2 success**，各返回 2 个 pack，无 community failure；
- 报告有 Stack Overflow 引用，raw/gap=0；
- health 仅来源集中 warn，无 invalid。

## 4. 独立 6 例整体复测

对同一独立 6 例（F200-001/021/049/137/177/117）在修复后整体复跑：

- 6/6 complete，约 11 分钟，374,260 tokens；
- **community 6/6 success**（修复前为 4/6），每例 2 个 pack；
- **6/6 报告引用 Stack Overflow**，raw/gap=0；
- health 无 community failure；仅来源集中/official 页面 warn；
- 结论：该独立样本上，可靠性修复有效；仍不能外推所有外部故障。

## 5. 限制

- 只复测 2 例失败 + 6 例整体，不能证明所有外部故障消失；链路上仍可能出现 resolver/网络/timeout；
- 8 次预算和 source-level 重试会增加少量 API 请求/时间，需在最终 200 观察；
- 不改 legacy 回退路径。
