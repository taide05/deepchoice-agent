# DeepChoice：恢复线接续交接

更新：2026-10-25。用户已明确放弃约3866测试的 durable 开发线。
本页纠正此前 Codex 交接把该线重新指定为产品基线的错误；不为用户和 dsh 制定新研发路线。

## 使用哪份代码

| 角色 | 路径、分支与代码身份 |
|---|---|
| 恢复线的现存接续位置 | `D:\deepchoice-precodex`，`precodex/deepseek-adapter`，代码提交 `b080213ea2267a1c48b06142b105540c7581c4d6` |
| 恢复线起点，仅供追溯 | `48b32bdbb46a7c869c61798d30c3bd9cf8da631f`；Git reflog 显示分支于2026-10-14建立，其后包含 DeepSeek 适配和已完成的恢复线修复 |
| 已放弃的 durable 路线 | `D:\deepchoice-agent`，`codex/generic-selection`；`fef61b8` 是该线旧候选，不是接续基线 |
| 错误交接后新增的工作 | 同树 `7da3701`、`ae5f3f3` 及 `.scratch/r10_round2/`、测试日志；保留，不默认移植 |
| 旧工作树和历史材料库 | `D:\deepchoice-dsh`，`dsh/subtraction-repair-20261012`，`50baaba`；不是恢复线工作区 |

本次核对时恢复线仍为 b080213，仅有 learned_docs.json 用户修改和17项既有未跟踪材料。
随后本次交接若形成文档提交，HEAD 可以改变；生产代码仍以 b080213 为核对基点。
48b32bd 是历史恢复起点，不能把“回到恢复线”误解为 reset 到该提交、删除其后成果。
路径名字里的 agent/precodex、代码新旧、测试数量都不能替用户决定开发版本。

## 先解除错误的工作区绑定

停止在已放弃分支上新增修改和派发；已有任务如仍运行，先按其真实状态妥善结束并记录，
不要批量杀 Python、删除输出或把未知提交当成未执行。未完成改动保留原地并简记。
切换 dsh 的实际工作区到 `D:\deepchoice-precodex`，在那里读取 AGENTS.md 与本页。
不只在旧会话里 cd 后继续继承 durable 规则。复核分支、HEAD 与用户修改即可，不重做全仓审计。

恢复线实际 API 为 `POST /research` 及 `/research/{task_id}/...`，前端在本树 frontend/app.py。
不再要求它接入 `/api/v1/tasks/*`、恢复 durable 的3866项测试或接入 final_batch 才能继续。
这些功能如未来有需要，由用户与 dsh 主动选择，不由旧交接自动引入。

## 防止换目录后仍导入错误代码

共享环境 `D:\deepchoice-agent\.venv` 的 editable 安装指向另一工作树。使用其解释器不等于
使用其源码；必须显式指定当前树源码，核对导入路径。以下是无需启动服务的本地核对：

```powershell
Set-Location D:\deepchoice-precodex
$env:PYTHONPATH = 'D:\deepchoice-precodex\src;D:\deepchoice-precodex'
D:\deepchoice-agent\.venv\Scripts\python.exe -c "import deepchoice; print(deepchoice.__file__)"
```

打印路径应在 `D:\deepchoice-precodex\src` 内。不要为了切换代码覆盖共享 venv 或全局 Git 配置。
既有本地 `serve_precodex.py` 已显式设置本树源码、工作目录、8100回环端口，并从另一树的
.env 读取凭据；它是启动入口参考，不由本交接自动执行。服务启动可能预加载模型或外呼。
前端单独设置 `API_BASE=http://127.0.0.1:8100`，并从本树运行 frontend/app.py；后端子进程的
环境不会自动传给另一个前端终端。每次实际运行记录所用版本，避免服务与前端串到其他树。

## 哪些成果可以继承

恢复线已有来源采集、共享证据、报告/引用和条件决策等实现；第7/8轮决策修改已包含在 b080213。
历史交付记载668项测试通过，本次没有重跑，也不据此声称内容达标。
恢复线第12次配对两臂正式门槛未通过，原报告、评分和 seal 保留。其来源覆盖、回答质量和
展示体验可供用户与 dsh 判断下一步，但不自动启动旧的轮次、晋级或停止流程。

以下材料属于另一条已放弃路线，按需参考，不是本树的已证实故障清单：
- `D:\deepchoice-dsh\r10_diag2\`：fef61b8 的 A-02/E-01 验证链诊断和已用额度。
- `D:\deepchoice-agent\.scratch\r10_round2\`：错误接续后的记录；用量按实际产物另行对账，不能抹掉。
- `7da3701`、`ae5f3f3`：可参考思路，不整包 cherry-pick，不把其测试失败拿来修本树。
- durable 状态机、5/4事实容量、source_checks、final_batch、132题计划：均不能默认成为恢复线要求。

各树 learned_docs、.env、数据库、历史报告、stash 和未跟踪材料保持原状。不整体搬动工作树。
此前D盘根目录三组临时材料已经归档到
`D:\deepchoice-dsh\.scratch\root-folder-archive-20261025`，不用再次整理。

## 用户与 dsh 直接决定下一步

尽快让个人项目可用、可展示并形成真实指标。下一目标、路线、预算、样本量和验收由用户与
dsh 商定；Codex 不再负责审批。已委托范围内连续实现、调试、复测，可复用失败题和现有材料，
不要求逐例批准、独立准备者、seal、多轮复核或每包全套。验证针对实际改动与用户输出。
可以调整/删并提示、节点、来源选择、自审及报告结构，不以保留旧架构为目标。
真实结果、秘密、用户数据和实际预算仍照实保护；unknown 不伪装成 verified。

本次只纠正基线与交接，不增加或重置额度。若用户已经在 dsh 明确授权新工作，保留其有效范围，
核对已用部分后继续；不因换工作区再把已消耗额度变成余额，也不无故要求重复批准。
接手后简短说明实际采用的代码和现有能力，再与用户继续产品讨论；不另开交接审计项目。
