# 本地清理归档（不纳入代码提交）

这些文件来自本轮及此前一批临时导出、复核探针与测试临时目录。
归档目的是保留其中**唯一且仍有价值**的复核结论、失败证据与必要脚本，
原目录随后按清单删除。**本目录不加入任何代码提交。**

清理执行时间：2026-10-16（本轮），冻结提交 `11ffd39`。

| 归档子目录 | 内容 | 原路径 |
|---|---|---|
| `review-probes/` | 独立复核代理使用的探针脚本（把复核结论变成可复跑的证据） | `D:\dc-review-1b4a4cb\*.py`、`D:\dsh-tmp\*.py`、本工程根目录 `_*.py` |
| `proxy-probes/` | 早期阶段的路由/归属/前端证据探针 | `D:\dc-run-head\*.py` |

## 为什么这些值得保留

- **复核结论的证据来源**：本轮与上一轮的独立复核结论（阻断项、假测试、inert 修复）
  都是靠这些探针在保存材料上实测得出的；保留它们才能复现结论，
  而不是只留一句"复核说不通过"。
- **项目根目录的 `_*.py`**：这是本轮各验证脚本（`_endpoint_verify.py`、`_leak_verify.py`、
  `_identity_verify.py`、`_payload_check.py`、`_slow_verify.py`、`_acceptance.py` 等）
  的实际代码；它们**未提交**，删除导出目录后若不归档就会永久丢失。

## 不归档的内容及原因

- `bt-*/`、`base48/`、`head/`、`cwd-*/`、`base-*/`、`prev*/`、`cur-*/`：
  由 `git archive` 导出或由 pytest 生成的**可重建**副本与临时数据。
- `benchmarks/cases_*.json`：仓库内已有同版本文件，属重复副本。
- `.zip` 包：与其解压目录同源，二者皆可重建。
- `__pycache__/`、`outputs/fake_task_1/`：运行缓存与测试产物。

## 原路径清单（核实用）

| 原路径 | 类型 | 结论 |
|---|---|---|
| `D:\dc-1b010f4` | 目录，`git archive 1b010f4` 导出 | 已删（可重建） |
| `D:\dc-1b010f4.zip` | 压缩包 | 已删（与上同源） |
| `D:\deepchoice-baseline-48b32bd` | 目录，`git archive 48b32bd` 导出 | 已删（可重建） |
| `D:\deepchoice-baseline-48b32bd.zip` | 压缩包 | 已删（与上同源） |
| `D:\dc-review-1b4a4cb` | 复核代理工作目录（含导出、basetemp、探针） | 探针已归档，目录已删 |
| `D:\dc-run-head` | pytest basetemp + 探针 | 探针已归档，目录已删 |
| `D:\dc-run-1b` | pytest basetemp（空/仅临时数据） | 已删 |
| `D:\dc-run-48` | pytest basetemp（空/仅临时数据） | 已删 |
| `D:\dsh-tmp` | 复核代理临时目录 + pytest 数据 | 见"暂缓/时序"说明 |
