# O1：模型输入缓存成本拆账

日期：2026-09-16。范围：仅补用量观测及复核已有开发运行；不改 Prompt、检索、评分数据集、预算或调度，不启动付费研究。模型输入缓存与 SQLite 检索缓存分开。

## 新记录契约

- 共享 `call_model`、冲突补证工具 LLM、最小兼容探测统一提取 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`。只接收非负整数（不接收 bool、浮点、字符串），两项之和必须等于输入 token；不持久化任意 SDK 字段。
- 支持官方 `prompt_tokens_details.cached_tokens` 别名：仅在 native 两项都不存在时，由已知输入减去已知 cached 数得到 miss；native 缺项、显式 null、类型错误、矛盾或别名不一致均保留 unknown，不借别名补救。
- Trace 仍 best-effort。公开调用含缓存分项及 `cache_usage_complete`；run 总计含两项的**已知小计**、`cache_usage_known_calls`、`cache_usage_complete`。只有所有 LLM 调用分项完整且输入大于零时才给命中率，否则为 null。失败/重试/未结束调用同样进入完整性分母。
- 采集器新增 run 级分项及 `usage-by-node.csv`，按 node/attempt 分组保留所有调用和重试；历史缺归属记录标 `unattributed` / attempt 0（未知，不是实际尝试号）。非最终采样禁止完整性通过及命中率声明。
- Streamlit 展示已知命中/未命中小计与分项完整的调用数；旧服务/旧数据仍可读取，缺失为破折号。旧 graph usage 行维持兼容形状，字段缺失表示未采集；有已知分项的新 graph 汇总才携带缓存小计/完整性。
- **预算照常扣总 token，不对命中输入打折。** 金额沿用冻结的 `unpriced-v1` unavailable，不套用未经核对的价目表。未做 LLM response cache、缓存预热或提示词填充。

字段及输入恒等式依据：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。提供方缓存是输入前缀匹配、best-effort；不能把本项目检索缓存命中率当作模型缓存命中率。[官方缓存说明](https://api-docs.deepseek.com/guides/kv_cache/)

## 已有六次运行：能确认什么

样本：`product-baseline-v1` 1.0.0（冻结 2026-09-16），P01/P06/P07 各两次；测量版本 `e25610b4cc013274ae45e5cd4184901a2f78f14a`。数据集/manifest/environment/资产身份与逐 run 原件绑定见 [O1-R 安全记录](o1r-single-case-observations.json)。本次只读它列明的六个 latest collection，不修改历史 runs/CSV/数据库。

| 节点 | LLM 调用 | 已知输入 | 已知输出 | 已知总 token |
|---|---:|---:|---:|---:|
| conflict_detector | 131 | 72,395 | 7,215 | 79,610 |
| conclusion_synthesizer | 6 | 36,720 | 6,689 | 43,409 |
| self_reviewer | 6 | 10,780 | 2,231 | 13,011 |
| query_adapter | 6 | 3,052 | 2,850 | 5,902 |
| multi_retriever（官方 URL fallback LLM） | 18 | 1,332 | 90 | 1,422 |
| 合计 | 167 | 124,279 | 19,075 | 143,354 |

6/6 最终总用量完整；模型缓存分项采集 **0/167 调用，0/6 run**。命中输入、未命中输入与命中率都是 unknown，不是 0；不得从总输入反推未命中输入，也不能把已知输入当成未命中成本。

输入占总 token 86.7%；冲突处理 + 合成占输入 87.8%。这是**输入量热点**，不是未命中输入/金额热点已经证实。六次均无 LLM 重试；来源仍 degraded（1/78 scholarly 逻辑检索/工具调用失败），没有货币成本对账。

## 下一次观测与优化边界

下一次另经决定的单例运行，应核对调用分项恒等式、调用/节点/run 小计一致、缺失调用数量、最终采样以及来源健康。旧六次不补跑，不重写为“已采集缓存”。新实现尚未作付费端到端缓存分项验收。

先用已有 [报告核验](o1-development-report-review.md)定位无关证据与伪强证据；后续 O2 再独立冻结“减少无关/重复输入、保留决定性证据”的候选假设。优先目标是降低同等质量下的未命中输入和实际成本，不以提高命中率本身为目标。不将本轮观测补齐声称为节省已发生。

## 验证与交付记录

2026-09-16，Windows / 项目本地 Python 3.12.4：

- 相关聚焦测试 92 passed；前端测试 31 passed。最终补齐别名类型边界后，缓存/前端聚焦测试 49 passed（48.09 秒）。这些集合存在重叠，不累加为独立覆盖分母。
- 最终代码及测试冻结后的全套测试 **1142 passed / 0 skipped，218.18 秒**。此前一轮因收尾静态清理与补充测试主动中止，不计验收结果。
- pyflakes（src/tests/benchmarks/frontend）、vulture（src，100% confidence）、pip check、git diff --check 均通过。`smoke-v1` 固定 fixture replay **12/12 passed，baseline_matches=true**，fingerprint `0e4dd8d574ea8554881eb7f39039e0a1131320f547b22e7cae382e83825ef919`；无 LLM/网络，不能视为真实 12-case 产品评测。未验证 Linux/Python 3.11 的远程 CI 矩阵。
- 六份报告、六份 public snapshot、run/experiment/manifest 及 canonical 冻结数据集身份 6/6 校验通过；没有修改原件或读取保留集报告。
- 独立助手复审无阻断项；别名 bool/float 漏洞已修复并复现关闭，预算仍按总 token。针对三个关键报告问题完成独立复核，其余暂定评分未逐项独立重评，未作人类校准。
- 本轮新研究 run / 模型 API 调用均为 **0**；仅清理本轮明确的测试临时目录，不删除历史评测、知识库或运行数据库。

离线通过不代表提供方一定返回缓存分项，也不代表 O1/并发/真实质量已验收。付费批次继续暂停，累计额度仍 43/48，剩余 5 不自动使用。
