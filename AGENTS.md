# DeepChoice：本工作区身份纠正

更新：2026-10-25。用户最新决定优先。

本目录 D:\deepchoice-agent / codex/generic-selection 是用户已放弃的durable开发线。
此前把fef61b8/150b0c6指定为继续开发基线的交接错误已撤回。
本树保留作历史实现和数据参考；不因工作区自动加载了本文件就继续修这条路线。

实际接续工作区：D:\deepchoice-precodex / precodex/deepseek-adapter，代码基点b080213。
先读 [纠偏交接](docs/next-session-product-optimization-handoff.md)，再在恢复树读取其
AGENTS.md和HANDOFF.md。历史恢复起点48b32bd不等于reset目标，不删除其后成果。

切换前保留本树用户修改、7da3701/ae5f3f3新增提交、运行和测试材料。不要自动移植、恢复stash、
重跑全套、批量停止进程或清理数据。若有进行中的任务，按实际任务状态妥善结束并记账。
用户若另行明确要求修改本树，可在该范围内操作；本说明不阻止明确授权的文档更正和取证。

本树README、docs、测试和durable运行契约仅描述本树实现，不作为恢复线的任务或架构要求。
共享Python环境的editable安装指向本树，恢复线必须显式核对导入路径，不能只换cwd。

用户和dsh直接决定目标、路线、预算与交付，无需Codex审批。旧轮数、固定晋级和每包全套
不再是约束。普通实现与失败可在已委托范围内连续处理，保留真实结果、实际用量及用户数据。
不擅自reset/restore/stash/amend/rebase或覆盖他人改动；不批量暂存learned_docs、秘密、
数据库、输出或历史材料。临时材料放所属工作树.scratch，push/发布依用户明确要求。

本文件此前的宽松工作方式在恢复树AGENTS中保留；这里只纠正适用版本，不恢复旧审批流程。
