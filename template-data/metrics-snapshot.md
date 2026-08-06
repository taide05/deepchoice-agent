# 指标快照

> 供 R 模板（README 更新）和 B 模板（面试准备包）消费。
> 每次 V 执行后更新"最新"段，旧值移入"历史"段。历史段保留最近 5 次快照。

## 最新
- 日期：2026-08-06
- 触发：三问题修复 → E' 100 case 验证 → V(门禁)
- Commit：a02c384
- 测试：87/87 passing
- 测试：87/87 passing
- I 修复项：str.get guard (B1) / /tasks endpoint (B2) / confidence criteria relax (B3) / judge prompt widen (O1) / agent timing (O2) / source split (O3) / clarify flag (O4) / anti-bias prompt (O5)

| 指标 | 值 | 来源文件 | 可复现 |
|------|-----|---------|:--:|
| Top-1 准确率 | **75.9%** | E' 100 case (benchmark-20260806-024842) | yes |
| 任务成功率 | **96.0%** (96/100) | 同上 | yes |
| 声明溯源率 | **90.5%** | 同上 | yes |
| 信源召回率 | **75.4%** | 同上 | yes |
| official_doc 召回率 | **80.9%** | 同上 | yes |
| 冲突检测率 | **15.6%** (14/90) | 同上 | yes |
| 端到端延迟 P50 | **264.7s** | 同上 | yes |
| 端到端延迟 P95 | **419.8s** | 同上 | yes |
| 报告质量 A 级率 | **96%** | report_quality.py 实测 | yes |
| 代码测试 | **87/87** passing | pytest 实测 | yes |
| Docker 部署 | 2 容器 PASS | C 实测 | yes |

## 历史
| 日期 | 触发 | Commit | 关键指标变化 |
|------|------|--------|-------------|
| 2026-08-05 (pre-fix) | 全链路 D→E | — | E 200 case: Top-1 74.9%, P50 149.9s, P95 203.4s, 99% success |
| 2026-08-04 | I→V(门禁) | 42f82a8 | 旧 100 case: Top-1 79.8%, P50 184s, P95 248s |
| 2026-07-31 | 初始快照 | 455e805 | P50 162.6s→130.5s，P95 410.3s→164.2s |
