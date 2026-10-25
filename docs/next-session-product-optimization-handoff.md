# 交接纠正：不要在此树继续已放弃的路线

更新：2026-10-25。此前本页指定 `D:\deepchoice-agent` / `fef61b8` 为接续产品基线是
Codex的交接错误。用户已明确放弃约3866测试的durable路线，继续此前恢复线。

**唯一接续入口：** [D:\deepchoice-precodex\HANDOFF.md](../../deepchoice-precodex/HANDOFF.md)。
实际工作区为 `D:\deepchoice-precodex`，分支 `precodex/deepseek-adapter`，代码基点
`b080213ea2267a1c48b06142b105540c7581c4d6`。恢复起点48b32bd仅供追溯，不执行reset。

错误交接后在本树产生的 `7da3701`、`ae5f3f3`、运行材料和测试日志原样保留，不默认移植。
本树的durable接口、3866项历史测试和r10_diag2诊断不成为恢复线的任务、能力或质量成绩。
本树后续文档提交不改变上述代码归属；不要根据“最新HEAD”再次选错工作区。

切工作区还要核对Python实际导入路径。共享venv默认editable路径可能仍指向本树，纠正方法
见新交接。不要只换终端目录后继续沿用旧AGENTS和durable启动说明。

用户与dsh直接决定后续目标、路线和资源，不需Codex审批。已授权委托在实际剩余额度内继续；
本次纠偏不新增额度，也不重置已用额度。当前所有用户修改、历史结果、数据库和stash保留。
旧目录归档位置仍为 `D:\deepchoice-dsh\.scratch\root-folder-archive-20261025`，没有再次移动。

本页旧版本可用 `git show 150b0c6:docs/next-session-product-optimization-handoff.md` 查阅，
它是错误交接的历史记录，不再作为操作指令。新交接已列出三个工作树与各份材料的适用范围。
