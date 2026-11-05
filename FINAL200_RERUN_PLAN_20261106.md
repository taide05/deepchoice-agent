# 最终版正式 200 重跑计划（谷价窗口，2026-11-06 00:30–08:30）

> 用户决策（2026-11-05）：采用方案 B —— 用最终代码从零重跑正式 200；追加 16M tokens（总上限 40,000,000）；
> **运行必须落在 DeepSeek 谷价窗口内**（北京时间 00:30–08:30，UTC 16:30–00:30）。
> 2026-11-05 更新：原 Windows 定时任务已按用户要求删除；改为**用户通知后立即手动启动**，仍须在谷价窗口内。

## 1. 运行配置

| 项 | 值 |
|---|---|
| 题集 | `.scratch/cases/cases_formal_200.json`（200 例固定分母，SHA `46728f20…`） |
| 失败策略 | 固定题集一次跑齐；基础设施失败**重跑原案例**，不替换；invalid 案例同案例重跑并披露 |
| 代码 | 当前 HEAD（含修复：抓取兜底/32k 预算/规则 35–46/v1.2.3 严格契约；commit 以启动时实际 HEAD 记录） |
| 配置 | `EVIDENCE_INPUT_BUDGET_CHARS=32000`；并发 4；timeout 1800；token 上限 16,000,000 |
| 输出 | `.scratch/cases/runs/final-200-finalcode-20261106` |
| 启动 | **由用户手动触发**（原定时任务已于 2026-11-05 按用户要求删除；用户会通知实际运行时间） |
| 预计时长 | 约 4–5 小时（并发 4，单例 wall p50 ≈ 250–450s），预计 04:30–05:30 完成 |
| 预算 | 计划 ≤16M；总上限 40,000,000（已含此前 22,738,695） |

## 2. 启动脚本

`.scratch/cases/run_final200_offpeak_20261106.ps1`：设置 PYTHONPATH/预算 env → 运行 run_batch →
完成后自动执行 gate 检查、确定性指标、review-ready 准备 → 写 `OFFPEAK_RUN_DONE.json`。
日志：`.scratch/cases/runs/final200-offpeak-20261106.log`。

## 3. 启动后流程（窗口内尽可能完成）

1. **Gate**：200/200、health invalid=0、provenance 完整（脚本已自动跑）；
2. **确定性指标** + review-ready（脚本已自动跑）；
3. **评审**：内部全量 200（C1–C4 + D1–D5，v1.2.3 严格契约）→ 独立复核 200 → 一致率；
   评审 agent 走会话额度，建议在谷价窗口内继续跑；
4. **第三层抽检**：由用户把新的抽检口令交给第三层 AI（针对新批次新报告）；
5. **交付包最终版**：仅在第三层复检通过后生成，状态标"最终验收通过"；否则保持暂缓并披露。

## 4. 启动方式（手动，用户通知后执行）

```powershell
$env:PYTHONPATH='D:\deepchoice-precodex\src;D:\deepchoice-precodex'
$env:EVIDENCE_INPUT_BUDGET_CHARS='32000'
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py --cases .scratch\cases\cases_formal_200.json --out .scratch\cases\runs\final-200-finalcode-20261106 --concurrency 4 --timeout 1800 --max-tokens 16000000
```

运行完成后自动/手动执行：gate → 确定性指标 → review-ready（见 §3）。

## 4.1 前置条件与风险

- 计划任务为 **Interactive only**（Windows 要求登录会话）：请保持电脑开机且当前用户已登录；
  休眠会阻止启动（已设置 WakeToRun，但系统休眠/关机仍会失败）；
- 若任务未启动（日志无新内容/无输出目录），用户可用同样命令手工启动，仍在窗口内；
- 若运行超出 08:30，后续评审不再享受折扣价（可接受，运行本身在窗口内）；
- 失败或 402 即停，保留现场并更新 `NIGHT_RUN_STATUS_20261103.md`。

## 5. 验收口径（不变）

- 200 固定分母、无替换；invalid 必须重跑或明确计为失败；
- `usable = C1 && C4==0`；`decision-grade = usable && C2 && C3`；C2 按 v1.2.3 五项 + 可比性判定；
- 最终报告披露：完整性、tokens/耗时、置信度、官方证据、评审三层（含第三层抽检）、限制与混合批次 provenance；
- 新旧指标不可混用（旧冻结批仅历史基线）。
