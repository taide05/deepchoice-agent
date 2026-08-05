# DeepChoice D-full：复盘闭合（第 7 节）

> 执行时间：2026-08-05 | 消费 D-light + E + C 产出

---

## 7.1 设计决策验证回填

| D 决策# | 决策 | E 是否验证 | E 实测结果 | 与 D 预期一致？ | C 工程验证 | 验证结论 |
|:--:|------|:--:|------|:--:|:--:|:--:|
| 1 | 9 Agent LangGraph 管线 vs 单次巨型 Prompt | 部分 | P50=150s, P95=203s（D 预期 150-200s→P50 刚好在边缘，P95 超了 3s） | ⚠️ 偏差——P50 落在地板值 150s，说明大部分 pipeline 开销已到理论下限。变体 case 无明显 retry | C17 ⚠️ 未完成 9 Agent 全调用验证（E 已验证） | ⚠️ 部分验证 |
| 2 | 信源评分用规则引擎而非 LLM | 部分 | E 未执行确定性验证（跑两次对比）。但 report_quality 的 winner_extractable=100% 间接证明评分输出稳定 | ➖ 无法判断——未跑确定性测试 | C ✅ 无硬编码 Key（不涉及 LLM 评分） | ➖ 未验证 |
| 3 | 两阶段冲突仲裁（flash 批量 + pro 深裁） | 是 | P95=203s < D 预期 250s ✅。冲突检测率 0%（LLM judge 太保守）→ 但管道仍正常运行 | ✅ 一致——延迟指标支持决策#3 | C ✅ 管道运行正常 | ✅ 已确认 |
| 4 | 前置澄清模块混合式+软门禁 | 否 | E 未跑澄清 A/B 对比 | ➖ 无法判断 | C ✅ 澄清模块路由正常 | ➖ 未验证 |
| 5 | SelfReviewer 最多重试 1 次 + 三级缺口路由 | 是 | retry_mean_delta=0→几乎无 retry。99% 成功率→max 1 次约束未被突破 | ✅ 一致——如 D 预期，retry 触发率极低（2/200） | C ✅ | ✅ 已确认 |

---

## 7.2 模块指标更新

| 指标 | D-light 引用值（README 100 case） | E 实测值（200 case） | 差异 | 需更新 README？ |
|------|------|------|:--:|:--:|
| Top-1 准确率 | 79.8%（67/84） | **74.9%**（131/175） | **-4.9pp** | **是**——旧数据过时，且 200 case > 100 case，新数据更可靠 |
| 任务成功率 | 97.0%（97/100） | **99.0%**（198/200） | +2pp | **是** |
| 声明溯源率 | 97.0% | **99%** | +2pp | **是** |
| 冲突检测率 | 2.2% | **0.0%** | -2.2pp | **是**——需加注释说明 LLM judge 保守性 |
| P50 延迟 | 184s | **149.9s** | -34s（-18%） | **是** |
| P95 延迟 | 248s | **203.4s** | -45s（-18%） | **是** |
| 信源召回率 | 34.8% | **38.4%** | +3.6pp | **是** |
| 报告质量 A 级 | 97% | **97%** | 持平 | 否 |
| 测试数量 | 87 tests | **87 tests** | 持平 | 否 |

> **重要变更**：基准规模从 100 case → 200 case。README 中所有"100 case"引用应更新为"200 case"。

---

## 7.3 踩坑修复确认

| D 踩坑# | 坑 | E 是否复现 | C 是否验证仍有效 | 当前代码状态 | 状态 |
|:--:|------|:--:|:--:|------|:--:|
| 1 | 否定词匹配 100% 假阳性 | 否——E 显示 LLM 语义扫描生效，冲突检测虽 0% 但无假阳性 | C ✅ | commit `455e805` 的修复仍在，否定词匹配代码已完全移除 | ✅ 已修复，无回归 |
| 2 | conclusion_synthesizer flash 质量不足 | 部分——E 的 winner_extractable=100% 证明 pro 模型有效。但 confidence=low 系统性问题显示 SelfReviewer 仍有质量盲区 | C ✅ | commit `6631bbc`（flash→pro）的修复仍在 | ✅ 已修复，但有新的 quality signal 问题 |
| 3 | Docker Windows wheels vs Linux 不兼容 | 否——C 的 Docker compose up 成功启动所有容器 | C ✅——2 个容器均正常启动，无构建错误 | commit `8d5773f` 的修复仍在，`42f82a8` 补了 env vars | ✅ 已修复，无回归 |

---

## 7.4 薄弱点验证

| D 薄弱点# | 薄弱点 | E 是否检验 | E 实测结果 | 面试追问风险重评级 | 备注 |
|:--:|------|:--:|------|:--:|------|
| 1 | 冲突检测率低——"模块是不是白做了" | 部分 | 200 case 冲突检测率 0%（vs D 预期 2.2%）。管道内日志显示大量"LLM scanning N candidate pairs"——管道在工作，但 judge 过于保守 | **维持高风险**（面试拷打点） | 需在 I 阶段修：LLM judge prompt 放宽匹配条件 |
| 2 | 信源召回率低——"还能叫 Deep Research 吗" | 部分 | 38.4%（+3.6pp vs 旧数据），但仍 < 40%。Official retriever 26 映射小幅改善 | **维持中高风险** | 需 I 阶段评估动态域名发现方案 |
| 3 | Agent 超时后管线不崩溃 | 否 | E 未 mock 超时场景。但 200 case 中 0 超时（TIMEOUT_PER_CASE_S=480s 足够） | **降为中风险**——480s timeout 在 200 case 中从未触发，实际超时风险低 | |
| — | **新薄弱点**：enterprise 场景准确率 | N/A | enterprise 场景准确率 62.3%（vs solo 79.3%, team 83.9%） | **高风险**——企业场景是"展示工程判断力"的核心场景，62% 难以说服面试官 | D-light 未覆盖此维度，I 需加 |
| — | **新薄弱点**：confidence=low 系统性 | N/A | 198/200 case confidence=low，仅 1 个 medium | **高风险**——面试官问"你怎么知道报告质量好坏"，如果回答"SelfReviewer 说了算"，对方追问"为什么全是 low"就崩 | SelfReviewer 的 6 项检查通过率与 confidence 评定脱节 |

---

## 7.5 断言清单验证状态

| D 断言# | 断言内容 | E 实测结果 | 验证状态 | 备注 |
|:--:|------|------|:--:|------|
| A1 | 9 Agent P50 150-200s | P50=149.9s | ⚠️ 部分（在 150s 边缘） | 150s 可能是 pipeline 序列化开销的理论下限 |
| A2 | retry_small 触发率 < 10% | retry_mean_delta=0 | ➖ 未验证 | 缺 retry_count 分布数据 |
| A3 | retry_full 触发率 < 5% | 同上 | ➖ 未验证 | |
| A4 | 同一 case retry ≤ 1 | 同上 | ➖ 未验证 | |
| A5 | 评分确定性 | 未跑两次 | ➖ 未验证 | E 待补项 |
| A6 | 两阶段仲裁 P95 ≤ 250s | P95=203.4s | ✅ 已确认 | |
| A7 | LLM 扫描假阳性 0% | 冲突 0%，无假阳性但过于保守 | ⚠️ 部分 | 无假阳性但真阳性也被过滤 |
| A8 | 澄清模块准确率差异 | 未执行 | ➖ 未验证 | |
| A9 | 澄清模块延迟 < 10s | 未执行 | ➖ 未验证 | |
| B1 | winner name 提取 100% | winner_extractable=100% | ✅ 已确认 | |
| B2 | Docker /health 200 | C4 验证通过 | ✅ 已确认 | |
| B3 | conflict_detector 无假阳性 | 未专门验证 | ➖ 未验证 | |
| C1 | 开放讨论冲突检测 > 15% | 未执行 | ➖ 未验证 | cases_200 全是 X vs Y |
| C2 | Official retriever 覆盖率 ≥ 50% | 未执行 | ➖ 未验证 | |
| C3 | Official retriever URL 可达 | 未执行 | ➖ 未验证 | |
| C4 | SelfReviewer 无 str.get bug | 2/200 FAIL（str.get） | ❌ 已推翻 | **P0 修复** |
| C5 | Agent 超时不崩溃 | 未 mock | ➖ 未验证 | |

**统计**：✅ 已确认 4 / ❌ 已推翻 1 / ⚠️ 部分 3 / ➖ 未验证 9

---

## 7.6 待修复清单（→ I 模板消费）

| # | 优先级 | 来源 | 问题 | 证据 | 修复建议 | 预估 |
|:--:|:--:|------|------|------|---------|:--:|
| **FIX-1** | **P0** | C-C9 FAIL + E-C4 ❌ | SelfReviewer `str.get` AttributeError 导致 2/200 case 失败 | E: TC-0004-v204, TC-0021-v221 均报 `'str' object has no attribute 'get'` | `self_reviewer.py` 的 `run()` 方法中检查所有 `dict.get()` 调用，确保调用对象为 dict 而非 str。加 `isinstance(obj, dict)` 防御 | 30min |
| **FIX-2** | **P0** | C-C9 FAIL | `/tasks/{task_id}` 端点缺失——客户端启动研究后无法查询状态 | `curl localhost:8000/tasks/1785915109` → 404 | 在 `app.py` 加 `GET /tasks/{task_id}` 端点，返回 status + thread_id + result（如完成） | 15min |
| **FIX-3** | **P0** | E 新薄弱点 | confidence=low 系统性——198/200 case 返回 low。SelfReviewer 6 项检查与 confidence 评定脱节 | E: benchmark 198/200 confidence=low | 审计 SelfReviewer 的 confidence 评定逻辑（`REVIEW_PROMPT`）。passed_count 与 confidence 映射可能过于严苛——passed 6/6 才给 high | 1h |
| **FIX-4** | **P1** | D 薄弱 #1 + E 退化 | 冲突检测率 0%——LLM judge 过于保守，已知矛盾全部 missed | E: conflict_detection_rate=0.0, LLM judge 0 keyword + 0 LLM | 修改 `CONFLICT_JUDGE_PROMPT`：放宽匹配标准，从"semantic overlap"改为"topic relevance"，降低匹配阈值 | 30min |
| **FIX-5** | **P1** | E 待补项 #1 | Agent 延迟拆分缺失——无法定位最慢 Agent | E: 实测覆盖率 Agent 拆分为 0% | 修改 `run_baseline.py`：加 `--profile-agents` flag，每个 Agent 调用处包裹 `time.perf_counter()` | 1h |
| **FIX-6** | **P1** | E 待补项 #2 | 检索源拆分缺失——无法区分 Tavily/GitHub/ArXiv 各自召回率 | E: 实测覆盖率检索源拆分为 0% | 修改 `run_baseline.py`：在 run_single_case 中记录每个 URL 来源（从 search_results 的 source 字段提取） | 30min |
| **FIX-7** | **P1** | C-C14 WARN | Docker 镜像未 pin digest | Dockerfile: `FROM python:3.13-slim` 有 tag 无 digest | 在 Dockerfile + Dockerfile.frontend 中 pin sha256 digest | 10min |
| **FIX-8** | **P2** | D 薄弱 #2 | 信源召回率 38.4%——仍 < 40%，Official retriever 需扩展 | E: source_recall=38.4% | Official retriever 从 curated list 改为：Tavily 搜索结果中提取官方域名 → HEAD 验证可达 → 加入映射。加 20 个新技术映射 | 1.5h |
| **FIX-9** | **P2** | D 新薄弱点 | enterprise 场景准确率 62.3%——vs solo 79.3%/team 83.9%，差距 17-22pp | E: enterprise 62.3% vs team 83.9% | 根因是 LLM 不充分考虑企业约束。短期：在 task 中加 `scene_context` 权重到 conclusion_synthesizer prompt。长期：加 scenario-aware scoring | 2h |
| **FIX-10** | **P2** | C-C15 WARN | 包版本过期——bcrypt 4.0.1→5.0.0, anthropic 0.111→0.120 | pip list --outdated | 逐包升级并跑 pytest 验证兼容性。bcrypt 注意 API 变更 | 30min |
| **FIX-11** | **P2** | C-C20 WARN | 无并发负载测试 | wrk 在 Windows 不可用 | 用 locustfile.py 跑基础并发（5/10/20 用户，30s ramp-up），记录 P50/P95/P99 延迟和错误率 | 1h |
| **FIX-12** | **P2** | E 退化 | "新贵偏好"——LLM 41% 错误选流行技术而非正确的 | E: 18/44 错误为"新贵偏好"模式 | 在 conclusion_synthesizer prompt 加反偏差指令："Prefer the technology that better fits the stated constraints over the more popular one" | 15min |

---

## 修复优先级统计

| 优先级 | 数量 | 描述 |
|:--:|:--:|------|
| P0 | 3 | 阻断——str.get bug + 缺失端点 + confidence 系统性 low |
| P1 | 4 | 本周修——冲突检测 0% + Agent/检索源拆分 + Docker digest |
| P2 | 5 | 下周修——召回率 + enterprise 准确率 + 包升级 + 负载测试 + 新贵偏好 |
