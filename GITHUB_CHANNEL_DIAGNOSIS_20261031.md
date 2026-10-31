# GitHub 通道诊断（2026-10-31）

> 针对 `final-200-20261031` batch-01 的 20/20 invalid。
> 零付费诊断；未跑新 case。

## 1. 症状

batch-01 所有 20 个 case 的统一错误：

```text
source_failed:github:
RuntimeError: no outbound channel available for source: github
```

同一时刻：

- tavily：success
- official：success
- community：success
- chroma/arxiv：empty/正常
- **只有 github 通道不可用**

## 2. 当前复测

用同一 `outbound` resolver 在当前环境预检：

```text
channel=direct
audit=[('github','local-proxy',False,'probe'),
       ('github','self-forward',False,'probe'),
       ('github','direct',True,'probe'),
       ('github','direct',True,'route')]
http=200
search_remaining=10 search_limit=10 core_remaining=60
```

结论：

- 当前 GitHub API 可达；
- resolver 会正确 fallback 到 `direct`；
- local-proxy/self-forward 未配置，所以 probe 失败是预期；
- 当前通道没有持续故障。

## 3. 判断

这不是代码/配置在本地永久失效，也不是全局网络故障：

- 上一轮最终 200（10/29）的 205 个 GitHub 结果全部 success；
- 本次失败只发生在 GitHub；
- 当前 GitHub 预检通过。

最可能的根因：

1. 运行窗口内 GitHub API/出站通道短暂不可用或返回 403/429；
2. resolver 会把失败 route 缓存并按 30/120/300s backoff；
3. `github_api.py` 在 `make_client("github")` 失败时没有 source-level retry，
   因此该 case 直接标失败；
4. 20 个 case 集中在同一窗口，全部落到同一个不可用 route；
5. 未配置 `GITHUB_TOKEN`，匿名 search 限额只有 10/min；
   probe 本身也消耗 search 配额，容易触发限流窗口。

## 4. 恢复前建议

1. **启动前跑 GitHub 预检**：
   `.scratch/cases/preflight_github.py`
   - 当前已通过；
   - 若失败则不要启动任何 case。
2. 最终 200 必须从 batch-01 重新跑，本次 batch-01 的 20 个 invalid 不能复用。
3. 可选：如果 GitHub 限流再次出现，提供 `GITHUB_TOKEN` 可把 search 限额从
   10/min 提高到 30/min；不需要把 token 发到聊天，只需在执行会话环境里设置。
4. 如果故障重复发生，再考虑给 `github_api.py` 加 source-level retry/backoff
   （这属于产品代码改动，需要重新冻结/测试，不在当前冻结范围内）。

## 5. 当前状态

- 最终 200 有效进度：**0/200**
- batch-01 失效，tokens 1,275,952 不计入最终结果
- 预检通过，但正式运行尚未恢复
- 无后台付费任务

## 6. 已实现的防护（2026-10-31）

### GitHub source-level retry

`github_api.py` 新增 `_make_github_client()`：

- `make_client("github")` 失败后：
  1. 调用 resolver.invalidate("github")；
  2. 等待 2s；
  3. 再解析一次；
- 两次都失败才抛错；
- 新增 `tests/test_github_retry.py`。

### GitHub 降为 optional source

`batch_health.py`：

- `OPTIONAL_SOURCES = {"community", "github"}`；
- GitHub 失败从 hard invalid 改为 warn；
- 原因：GitHub 结果只有 `has_body=False` 的导航/元数据，不是可引用正文；
- 本次 batch-01 重新审计：20 个 case 从 invalid 变为 **warn，0 invalid**。

### 启动前 guard

新增 `.scratch/cases/run_final_200_guard_preflight.py`：

1. 跑 `preflight_github.py`；失败则不启动任何 case；
2. 跑一个非最终 200 canary（C2-valkey-vs-redis）；
3. 检查 canary health 与 `search_results.github.status == success`；
4. 全部通过才启动 10 批正式 200。

canary 不进最终 200 分母，成本约 1 例。

### 测试

- 全量测试 **793 passed**；
- 预检当前通过；
- batch health 可选源变更后本次 batch-01 为 0 invalid。

## 7. 恢复条件

- 重新冻结恢复后的代码 HEAD；
- 必须用 `run_final_200_guard_preflight.py` 启动，不直接跑旧 runner；
- preflight 或 canary 任一失败则停止，不消耗 200 预算。

