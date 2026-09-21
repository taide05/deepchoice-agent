> 归档快照：2026-09-21。本文只保留当时事实与决策；其中“当前”“下一步”“待批准”均不是现行指令。
> 当前入口：[任务地图](../../current-roadmap.md)、[文档索引](../../README.md)。原文来源：40f9266 工作树。

# 基线准备检查与旧内容处理

日期：2026-09-16。审计起点：`8783d33`（仅用于定位）。范围：默认运行、测量入口、当前说明。
承接 [Phase 5-2 工程验收](../../phase5-engineering-acceptance.md)，未重新开展全架构重构。

## 结论

默认产品路径已采用 durable API 与统一 DeepSeek Flash；本轮重点清理会误导执行或污染数据的
旧工具入口。工程入口梳理已完成，真实基线尚待 O1 的采集器、案例冻结、运行环境清单和获批实测。
当前不能声称旧 benchmark 等同产品默认路径，也不能声称报告质量已改善。O1 已增加整任务
serial=1 / concurrent=12 的效果一致性验收；这不是 Locust HTTP 负载检查。

| 检查对象 | 证据与处理 |
|---|---|
| 默认运行 | Streamlit 使用 `/api/v1/tasks/*`；服务端 coordinator 接入产品库、checkpoint、Trace/Budget/cache；没有改回 legacy 路径 |
| 模型/恢复 | 上轮已统一 Flash，manifest 冻结配置；interrupted 与 pending HITL 的兼容检查已覆盖。保留历史身份，未改写旧运行 |
| 旧 benchmark | `run_baseline` 直接创建编排器并调用 judge，无 durable RunContext；新增 CLI 显式模式与全新输出目录要求，标记直连产物，修复原始异常泄漏和 Tavily 多 key 存在性提示 |
| 历史批次脚本 | 一个会删旧结果，另一个绑定全局 Python、吞错误并选择 latest；改成停用入口，旧实现留在 Git |
| 数据生成/合并 | 生成器导入即覆写案例、跨场景继承答案；改为无副作用入口。固定历史案例的合并 CLI 停用，避免混分母/偏向成功重试 |
| 手动 workflow | 原来执行旧 runner，固定读旧输出并套 Top-1 ≥85%、成功率100%；改为 fixture smoke，无 provider secrets/付费调用 |
| 只读负载 | 从旧 status 改为 durable GET，并显式将预期404视为成功；不宣称研究吞吐已验证 |
| 当前说明 | 更新 README 入口、历史命令标签、旧交接覆盖提示和设计文档历史状态；旧评价数字保持原日期/分母 |

## 保留与退出条件

- `/research`、legacy `search()`、旧模型参数适配：仍承担已承诺的兼容窗口，保留测试。删除前
  需明确版本窗口结束并核实调用方，而不是因为名称“旧”就移除。
- migrations、旧 manifests、运行/benchmark 结果、历史案例及验收报告：保留原样，不回填模型、
  不重算历史数字、不改 committed migration。生产库与用户 `.env`、缓存等本地状态未清理。
- 旧 metrics/judge/merge 函数：保留已知历史重算用途，在入口说明限制；O1 不复用它们的合并
  分母与缺失用量填零口径。Phase 5-2 已检查的分层回归测试继续保留，不为减少数量删测试。
- 依赖升级、企业级能力、安全端到端扩展等沿用 Phase 5-2 的剩余风险，不因本轮检查自动扩展。
- 本地主机将 Locust 导入已有异步/SSL 运行环境时出现 gevent Windows 原生加载错误及 SSL
  monkey-patch 冲突。只读回调以隔离 SDK 的单测验证；未宣称 Locust 本机可用或完成负载验收。
  若后续需要负载测试，应在独立受支持运行环境验证，不能在 pytest/API 进程中启动 gevent。

## O1 正式实测前必须完成

1. 已实现最小 durable API 采集器，离线覆盖超时取消、待决策、run 身份、用量缺失、结果采集
   与整 case 并发门；仍需在真实服务上完成一次无付费路径启动验收。采集器不读取 LangGraph 私表，
   也不复用旧 runner。
2. 已建立 12 例候选文件和人工评分字段；仍需人工核验参考依据、冻结版本/hash/日期，并落实
   开发集/保留集访问规则。候选状态会阻止付费采集。
3. 已提供 `benchmarks.product_baseline_server:create_app` 隔离产品/检查点数据库；仍需制作并记录
   只读知识库/learned-docs 快照，完成可重复启动验收。不能直接复用日常运行库宣称冷缓存基线。
4. 确认调用与费用额度后检查检索及 LLM JSON/tool/thinking 实际兼容性，再采集真实基线。
   `--health-check` 不请求 LLM，仅凭它通过不能认定模型适配已实证。
5. 正式额度按 12 例 × serial/concurrent 两个 profile × 2 次重复计算，最多 48 个研究 run；两次
   串并发配对均通过并发质量门禁后，才可声称 12 case 并发对产品效果没有显著损害。

## 验证记录

2026-09-16，项目 Python 3.12.4 环境：最终受影响聚焦集 26 passed；修复冻结后的全量套件
1075 passed、0 skipped；固定 smoke-v1 回放 12/12，fingerprint 匹配。pyflakes、vulture、
pip check、Compose 配置验证及文档链接检查通过；独立复审发现的诊断目录覆盖和 verbose 内容
泄漏问题已修复并复核，未发现剩余可操作问题。全量只在代码/测试再次修改后重跑。

本轮没有执行真实研究或付费 health check。Locust 原生加载问题按上述限制保留，未计为已解决。

O1 采集基础追加验证（2026-09-16）：8 个新增离线契约测试、45 个相关聚焦测试及完整套件
1083 passed、0 skipped；pyflakes 与 `git diff --check` 通过。没有执行真实检索、LLM 探测或付费
研究，12 例仍为 candidate，不能据此声称串并发效果一致。

O1 后续进度单独记录在[执行断点](../../o1-execution-status.md)：额度已确认、LLM 兼容探测及只读
路由检查通过；Chroma 路径隔离已修正。上述早期没有探测的记录仅描述其当时审计阶段，
不覆盖后续探测；真实研究仍为 0/48，案例冻结及主机稳定性尚未满足。
