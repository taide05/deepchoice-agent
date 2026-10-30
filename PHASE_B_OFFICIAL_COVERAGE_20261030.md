# Phase B：官方证据获取改进（2026-10-30）

> 本文件记录 Phase B（证据获取/来源身份）的零成本诊断与首轮实现。
> 没有跑新的付费批次；G1 实验需用户批准。

## 1. 零成本诊断

### 候选映射覆盖

对最终 200 的 400 个候选名做映射审计：

- 400/400 都能解析到 TECH_DOCS/learned 映射；
- 因此“官方正文缺失”不是映射缺失 alone，而是 **fetch/identity/页面形态** 问题。

### 官方正文覆盖（最终 200 snapshot）

| official_doc 正文页数 | case 数 |
|---:|---:|
| 0 | 9 |
| 1 | 16 |
| 2 | 40 |
| 3 | 33 |
| 4 | 42 |
| 5 | 35 |
| 6 | 15 |
| 7 | 10 |

- 9 个 case 完全没有 official_doc 正文；
- 16 个只有 1 页；
- 大量候选在一组 4 个 case 中持续 0 正文：
  Dependabot、Terraform、Echo、Text Generation Inference、Envoy、uv、msgspec、
  OpenSearch、InfluxDB、MySQL、Consul、Nomad、Go Fiber、Elasticsearch。
- C2 partial 中的高影响项：
  - F200-182：Pydantic v2 0、msgspec 0；
  - F200-184/181：msgspec 0；
  - F200-197：Kaniko 0；
  - F200-189/191：AWS CDK 仅 1，且是 AL2 relnotes 误入。

### 失败原因

按候选聚合的 fetch/identity 原因：

- `not_prose:navigation_like`：JS/SPA 文档 shell、目录页；
- `http:404`：映射 URL 过期/错误（msgspec、Hapi、Envoy 嵌套 fallback）；
- `http:403`：站点反爬（MySQL）；
- `content_encoding:gzip`：InfluxDB；
- `source_identity_unverified`：别名/重定向/派生页身份；
- `ConnectError/timeout`：网络/站点可用性。
- `not_prose:low_prose_ratio`：发布页/导航页。

## 2. 首轮实现

### 映射修正

- msgspec：`https://msgspec.dev/`（旧 `jcristharif.com/msgspec/` 404）；
- AWS CDK：`https://docs.aws.amazon.com/cdk/v2/guide/`；
- Terraform：`https://developer.hashicorp.com/terraform/docs`；
- Hapi：`https://hapi.dev/`（旧 `/tutorials/` 404）。

### GitHub raw README fallback

- GitHub repository 官方映射（如 Kaniko）在 HTML/rate-limit 失败时尝试
  `raw.githubusercontent.com/<owner>/<repo>/{main,master}/README.md`；
- 身份仍要求 owner/repo 完全一致 + README 正文命名候选。

### Static fallback 修正

- 不再对已经带 `/latest`、`/stable`、`/current` 的 docs URL 继续追加
  `/latest/`、`/stable/`；
- 避免 `/docs/envoy/latest/latest/` 这类 404；
- 对非空 docs path 不再盲目追加 `/docs/`、`/en/latest/`。

### Deep-doc 路径边界

- 新增 top path segment 约束：`docs.aws.amazon.com/cdk/...` 的派生文档不能跨到
  `/AL2/...`；防止 release-notes 正文提到包名就被当成 CDK 官方材料。

### Gzip

- `safe_fetch` 现在允许有界 gzip 解码（受 retained-byte cap 约束）；
- br/其他未支持编码仍在读取前拒绝。

## 3. 测试

- 新增/更新：
  - GitHub raw README fallback；
  - versioned docs root 不重复 latest；
  - top-path 边界；
  - 映射修正；
  - gzip 解码/br 拒绝；
- 相关测试全部通过；全量测试 **777 passed**。

## 4. 仍未解决

- `not_prose:navigation_like` 的 JS 文档站：需要更通用的 docs index / markdown
  入口，不是加 case 映射；
- `http:403`：站点反爬，不能强行绕过；
- `ConnectError/timeout`：外部可用性；
- 官方页面身份：部分需要更强的 page identity 数据；
- Gzip 解码只覆盖内容层，不保证站点返回可读正文。

## 5. 下一步（G1，需批准）

Phase B 首轮改动是一个 bundle（E2）。下一步应在开发集做一次 G1：

- 样本：20 例 expanded 开发集 + 6 例 independent；
- 目的：official body coverage、C2 partial 改善、C4/契约回归；
- 预算估计：约 **1.6M tokens**（历史 20+6 批次：1,212,857 + 374,260）；
- 上限：**2.0M tokens**；
- 不跑最终 200；
- 通过 G1 后再决定是否进入 Phase C，或是否需要第二次检索 bundle。

当前没有付费任务在跑。
