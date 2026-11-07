# 第 5 轮复审指令（同一独立审查会话使用）

> 第 5 轮抽检结论为"不通过"，blocker 为 B1–B4（c2_records_ok=false、doc_sync_ok=false）。
> 项目方已修复并更新材料；请在同一会话中**只做复审**（不必重跑新抽样，原 sample_pass 结论保持有效）。
> 仍是只读审查：唯一可写文件 `D:\deepchoice-precodex\ROUND5_RECHECK_RESULT_20261107.md`。

```text
继续你的第三层审查角色。项目方已针对你上一轮的 blockers B1–B4 修复，请执行复审：
1) 重新读 FINAL200_FINAL_RESULT_20261107.md（新增 §5）、BUDGET_LEDGER_20261107.md、
   review_final_200.json（应已更新，mtime 晚于 internal/independent fix4last 记录）、
   review_calibration/c2adj4.json、FREEZE_MANIFEST_20261107.json、DELIVERY_PACK_20261104/README.md 与 SUPERSEDED.md。
2) 逐项验证：
   B1：预算批准台账是否存在且自洽（40M→42.2M→42.4M 三档；实际 42,422,985；对 42.4M 超 22,985、对 42.2M 超 222,985），
       与 FINAL/FREEZE 口径一致；无未披露超支。
   B2：review_final_200.json 是否晚于两层记录；C2 规则是否书面化（修复集一致取一致、051/075/112/192 裁决）；
       按该规则独立重算 C2=true 应为 179、usable 199、DG 179；052/075/112/192 裁决结果是否与 c2adj4.json 一致。
   B3：F200-112 最终 C2 是否为 false（判据#2），相关记录是否一致。
   B4：FINAL 方案编号（带披露定稿=方案 C）与 174 类型标签（翻转门控不一致，report.md:94/100）是否已改正；
       交付包旧文件是否有 SUPERSEDED 标记、README 是否指向最终版本。
3) 只对受影响项复核（B1、B2 的 051/075/112/192、B4 文档），无需重新抽 10 例；原 sample_pass=true 保留，
   但需在结论声明"样本结论沿用第 5 轮，未重新抽样"。
4) 输出 ROUND5_RECHECK_RESULT_20261107.md：逐项 B1–B4 通过/不通过 + 依据（文件:行号）；
   重算指标；结论字段 repair_verified / c2_records_ok / doc_sync_ok / sample_pass（沿用）/ can_mark_final / blockers；
   声明 AI 辅助、非真人签字、样本不外推；若通过，写明"抽检验证通过（仅此口径）"。
5) 聊天里给 ≤250 字摘要（字段 + 结果文件路径）。
```

## 用法

把上面代码块整段发给正在担任第三层审查的那个 DSH 会话；它应输出
`ROUND5_RECHECK_RESULT_20261107.md`。把摘要贴回本会话即可。
