# 代码定位与可调整设计

> 2026-10-25 基线纠正：本页下文描述已放弃的 `codex/generic-selection` durable实现，
> 不是当前恢复线的开发指令或成绩。接续代码是 `D:\deepchoice-precodex` 的 `b080213`，
> 见[纠偏交接](next-session-product-optimization-handoff.md)。旧“当前/默认/下一步”只适用于本页原版本。

更新：2026-10-24。这是按需导航，不是接手前必须完成的审计清单。旧 911 行审计及 R0–R40
逐轮命令已移至 [原文归档](archive/retired-contracts-20261024/README.md)，其中 OPEN、下一步、
禁止新增、固定回放与复审要求不再给当前开发设门槛。

## 按用户问题定位

以下路径均相对 `src/deepchoice/`，不要只因文件多就重构全部模块。

| 用户问题 | 先看 | 可直接尝试的变化 |
|---|---|---|
| 取得材料却没进入回答 | `utils/fact_selection.py`、`utils/question_packet.py`、`agents/conclusion_synthesizer.py` | 简化来源选择，统一事实/问题表示，减少重复裁剪 |
| 有分析但保存前消失 | `utils/decision_analysis.py`、`utils/analysis_review.py`、`agents/self_reviewer.py`、`citations/` | 消除重复否决，细化拒绝原因，修复可恢复的结构问题 |
| 有条件偏好但用户看不见 | `utils/evidence_choices.py`、`formats/` | 对齐正文和结构表达，直接呈现条件取舍 |
| 资料单侧或同名噪声 | `retrievers/`、来源评分与事实选择节点 | 改进发现、归属及资料进入回答的顺序 |
| 用户提交/恢复/导出失败 | `server/app.py`、`services/tasks.py`、`runtime/`、`persistence/` | 针对实际故障修复产品链路 |
| 开发运行重复或额度不对 | 仓库 `benchmarks/final_batch.py` 及其 collector/ledger | 复用授权、预占与对账，避免另建控制平台 |

定位从当前报告、快照及阶段诊断开始。已有证据足够支持一个可回滚尝试时即可实施；
不要求先证明唯一根因、审完所有调用链或获得多轮评审。合理假设可实验，结果不支持就调整。

## 研究策略的选择权

当前 5 个来源、4 事实/行、联合生成、引用校准和自审只是实现。可保留、合并、替换或删去
效果不好的环节；也可以调整模型、提示、输出结构、容量和来源提升策略。
“原模块存在”“曾通过安全评审”“更保守”均不单独证明该产品策略值得保留。

不要把所有有据分析一律撤回视为默认正确；也不要为了保留分析伪造支持状态。
可独立成立的有据部分、明确的条件推断和待确认内容可以分别展示。具体表达由产品实现决定，
不再规定每次必须增加一个 gate 或质量分数。

## 已知诊断与证据界限

- A-02 最后一条条件选择被 source_checks 删除，值得直接检查验证链的保留/修复方式。
- E-01 五条分析均保留，条件偏好在正文中；其问题与 A-02 不同，还涉及来源与结构表达。
- 三条 shape 拒绝的具体输入未保存，原因尚不能细分。需要诊断时记录必要的脱敏结构和原因，
  不必因此建设全量 prompt/response 归档系统。
- 精确参考 URL 未取得不是完整语义覆盖率；以实际保存内容核对选择损失。

详见 [交接](next-session-product-optimization-handoff.md)。这里不指定 dsh 的修复顺序。
涉及状态、事务或费用控制时才查 [运行契约](phase1-runtime-contract.md)。
