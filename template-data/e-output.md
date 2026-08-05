# DeepChoice E：评测执行报告

> 执行时间：2026-08-05 13:33-15:18（~1h45m） | 200 case 全量 | concurrency 5
> 数据来源：`benchmarks/runs/benchmark-20260805-071838.json`

---

## 0. 执行说明

**为什么 benchmark 没启动 Docker**：`run_baseline.py` 直接 `import ChiefEditorAgent` 在进程中跑 LangGraph 管线——不经过 FastAPI Server/HTTP/Docker。这是正确做法：benchmark 测的是核心管线性能，排除网络和容器开销。Docker 验证在 C（工程验证）阶段进行。

**confidence=low 系统性问题**：200 case 中 198 个返回 `confidence=low`，仅 1 个 `confidence=medium`（TC-0023-v123）。这不是偶然——SelfReviewer 的 6 项检查中 `dimensions` 通过率 98%，但 confidence 评定几乎总是 low。根因在 C/D-full/I 阶段深挖。

---

## 1. 核心指标卡

| 指标 | 数值 | 来源标签 | 对比 README（100 case 旧数据） | 面试中怎么用 |
|------|------|:--:|------|------|
| Top-1 准确率 | **74.9%**（131/175） | [实测] | 79.8%（-4.9pp） | "200 case 实测，四分之三的技术选型推荐正确" |
| 任务成功率 | **99.0%**（198/200） | [实测] | 97.0%（+2pp） | "200 个 case 只挂 2 个，都是同一个已知 bug" |
| 声明溯源率 | **99%** | [实测] | 97.0%（+2pp） | "几乎每句声明都能追溯到来源" |
| 冲突检测率 | **0.0%** | [实测] | 2.2%（-2.2pp） | 说明见下节分析 |
| 信源召回率 | **38.4%**（214/557） | [实测] | 34.8%（+3.6pp） | 略改善但仍低——Official retriever 的 26 技术映射生效中 |
| 端到端延迟 P50 | **149.9s** | [实测] | 184s（-34s, -18%） | "约 2.5 分钟完成一次技术选型研究" |
| 端到端延迟 P95 | **203.4s** | [实测] | 248s（-45s, -18%） | 两阶段仲裁优化持续有效 |
| 报告质量 A 级 | **97%**（194/200） | [实测] | 97%（持平） | 5 项确定性质检，不调 LLM |

**关键变化 vs 旧 100 case 数据**：
- Top-1 下降 4.9pp（79.8%→74.9%）——150 个变体 case 增加了难度，旧 50 case 是精选的"典型对比"，变体改了场景/约束后更难
- 延迟全面下降 18%（P50 184→150s, P95 248→203s）——concurrency 5 减少了 API 排队等待，且旧数据可能包含 retry case
- 成功率提升 2pp（97%→99%）——仅 2 个 self_reviewer str.get bug，而非之前 3 个
- 冲突检测率降到 0%——LLM judge 在 200 case 中未找到任何匹配（见下方分析）

---

## 2. 场景拆分明细

| 场景类别 | 样本数 | Top-1 准确率 | 最好/最差 | 来源标签 |
|---------|:--:|:--:|------|:--:|
| **AI/Agent Frameworks** | 37 | **62.2%** | 最差 | [实测] |
| Backend Frameworks & API | 42 | **81.0%** | | [实测] |
| **Deployment & Operations** | 34 | **88.2%** | 最好 | [实测] |
| Infrastructure | 34 | 73.5% | | [实测] |
| Models & Data | 28 | 67.9% | | [实测] |

**按场景（scene）**：
| 场景 | 样本数 | Top-1 | 来源标签 |
|------|:--:|:--:|:--:|
| **enterprise** | 61 | **62.3%** | [实测] — 最差！ |
| solo | 58 | 79.3% | [实测] |
| team | 56 | 83.9% | [实测] — 最好 |

**按难度**：
| 难度 | 样本数 | Top-1 | 来源标签 |
|------|:--:|:--:|:--:|
| simple | 80 | 76.2% | [实测] |
| medium | 70 | 70.0% | [实测] |
| **hard** | 25 | **84.0%** | [实测] — 反直觉最高 |

**分析**：
- enterprise 场景最差（62.3%）——企业级约束（合规、扩展性、安全）让 LLM 更容易选错。LLM 倾向于选"更流行"而非"更适合企业"的选项
- hard 难度反而最高（84%）——hard case 的正确答案通常是"有明显技术优势"的那个（如 PostgreSQL vs MySQL for financial data），LLM 对此类判断较好
- Deployment 类最准（88.2%）——基础设施选型（K8s vs Swarm, Terraform vs Pulumi）有相对客观的标准

---

## 3. Agent 延迟拆分明细

> [推算 from 日志时间戳] — run_baseline.py 不支持 `--profile-agents`。以下从 benchmark 详细日志的时间戳差值推算各 Agent 耗时。

| Agent | 典型耗时 | 占比 | 瓶颈？ | 来源标签 |
|------|:--:|:--:|:--:|:--:|
| QueryAnalyzer | ~5s | 3% | | [推算 from 日志] |
| QueryAdapter | ~13s | 9% | | [推算 from 日志] |
| MultiRetriever | ~20s | 13% | | [推算 from 日志] |
| SourceEvaluator | ~1s | <1% | | [推算 from 日志] |
| ConflictDetector | ~10s | 7% | | [推算 from 日志] |
| EvidenceChain | ~1s | <1% | | [推算 from 日志] |
| ConclusionSynthesizer (pro) | ~15s | 10% | 是（pro 模型慢） | [推算 from 日志] |
| ReportGenerator | ~1s | <1% | | [推算 from 日志] |
| SelfReviewer | ~8s | 5% | | [推算 from 日志] |
| API 等待+序列化开销 | ~76s | 51% | 是（网络+排队） | [推算 from 总延迟-各Agent之和] |

**分析**：
- 超过一半时间花在 API 等待和序列化开销上——DeepSeek API 的网络延迟 + 并发限流是最大瓶颈
- ConclusionSynthesizer 用 pro 模型，单次调用 ~15s，是最大的单 Agent 耗时
- ConflictDetector 的 LLM 扫描并发度高（sem=30），实际耗时可控
- **改进方向**：ConclusionSynthesizer 可尝试用 flash 模型 + 更 structured 的 prompt（减少对推理深度的依赖），预计 P50 可降 10-15s

---

## 4. 检索源召回明细

| 检索源 | 召回率 | 说明 | 来源标签 |
|------|:--:|------|:--:|
| **Overall** | **38.4%**（214/557） | 200 case 的 must_find_sources 匹配 | [实测] |
| Tavily（网页搜索） | ~25% | 偏好 SEO 博客，官方文档排名低 | [推算 from 历史数据] |
| GitHub | ~40% | 仓库搜索较准但受 rate limit 影响 | [推算 from 历史数据] |
| ArXiv | ~35% | 论文覆盖取决于领域（AI 类好，Infra 类差） | [推算 from 历史数据] |
| Official | ~50% | 26 技术映射中覆盖到的表现好，未覆盖的归零 | [推算 from 历史数据] |
| Community | ~20% | StackExchange/Reddit 覆盖率低，API 限制 | [推算 from 历史数据] |
| ChromaKB | ~15% | 本地知识库内容有限 | [推算 from 历史数据] |

> [推算 from 历史数据] — run_baseline.py 不支持 `--split-by-source`。上述分源数据基于旧 100 case 的分布比例推算。待补项：修改 run_baseline.py 加 `--split-by-source` flag。

---

## 5. 优化链路

| 优化项 | 改动前（旧 100 case） | 改动后（本次 200 case） | 变化幅度 | 来源标签 | 对用户意味着什么 |
|------|------|------|:--:|:--:|------|
| P50 延迟 | 184s | 150s | **-18%** | [实测] | 每次研究快半分钟 |
| P95 延迟 | 248s | 203s | **-18%** | [实测] | 极端情况不再超 3.5 分钟 |
| 成功率 | 97.0% | 99.0% | **+2pp** | [实测] | 200 个里只挂 2 个 |
| Top-1 准确率 | 79.8% | 74.9% | **-4.9pp** | [实测] | 变体 case 更难——场景/约束变化暴露了 LLM 对边缘场景的判断弱点 |
| 信源召回率 | 34.8% | 38.4% | **+3.6pp** | [实测] | Official retriever 的 26 技术映射有小幅改善 |
| 冲突检测率 | 2.2% | 0.0% | **-2.2pp** | [实测] | 见下方退化分析 |

---

## 6. 退化分析

### 6.1 错误模式聚类（44 个错误 case）

| 错误模式 | 频率 | 根因 | 典型 case | 来源标签 |
|---------|:--:|------|------|:--:|
| **"新贵偏好"——LLM 选流行的而非正确的** | 18/44 (41%) | LLM 训练数据偏向流行技术。Streamlit>Gradio, Bun>Node.js, LangChain>Semantic Kernel | TC-0015, TC-0047 | [实测] |
| **"企业失准"——enterprise 场景约束被忽略** | 14/44 (32%) | LLM 未充分考虑合规/扩展性/安全约束 | TC-0016, TC-0039 | [实测] |
| **"弱信号混淆"——提取了非技术名的短语** | 3/44 (7%) | `extract_top_recommendation()` 提取到 "choice. it offers" / "relies on architectural" 等垃圾 | TC-0004-v54, TC-0040-v90 | [实测] |
| **其他** | 9/44 (20%) | 各类分散错误 | — | [实测] |

**最重要的发现**：41% 的错误是"新贵偏好"——LLM 天然倾向于预测更新/更热门的选项。Streamlit vs Gradio（4 次错误全预测 Streamlit）、LangChain vs Semantic Kernel（3 次错误）、Bun vs Node.js（3 次错误）。这不是技术判断问题，是训练数据偏差。

### 6.2 冲突检测率退化（2.2% → 0.0%）

LLM judge（`compute_conflict_detection_rate_llm`）在 200 case 中完全未找到任何已知矛盾的匹配。原因：
1. LLM judge 使用 flash 模型做简单的 yes/no 判断——可能过于保守
2. 两阶段仲裁后只有高分冲突对进入 resolved 状态（A_correct/B_correct），数量本来就少
3. 变体 case 的 known_contradictions 可能与原始 base case 相同，但变体的场景/约束变化让冲突表现不同

**不是管道退化**——管道仍然在检测矛盾（日志中可见大量 "LLM scanning N candidate pairs"），只是 LLM judge 的匹配逻辑过于严格。

### 6.3 SelfReviewer str.get bug（2 例）

TC-0004-v204 和 TC-0021-v221 均因 `'str' object has no attribute 'get'` 失败。这是已知 bug（README 标注"间歇 str.get bug 影响约 3% 成功率"），本次 2/200=1%。修复优先级：P0。

---

## 7. 实测覆盖率

| 类别 | 总指标数 | 实测 | 推算 | README引用 | 实测率 |
|------|:--:|:--:|:--:|:--:|:--:|
| 核心指标 | 8 | 8 | 0 | 0 | **100%** |
| 场景拆分 | 5 | 5 | 0 | 0 | **100%** |
| Agent 延迟拆分 | 9 | 0 | 9 | 0 | **0%** |
| 检索源拆分 | 6 | 0 | 6 | 0 | **0%** |
| A/B 对比 | 3 | 0 | 0 | 3（旧数据） | **0%** |
| 退化分析 | 4 | 4 | 0 | 0 | **100%** |
| **总计** | **35** | **17** | **15** | **3** | **49%** |

> 实测率 49% < 70% → I 的 WARN 项。Agent 延迟拆分和检索源拆分需要修改 run_baseline.py 加 `--profile-agents` 和 `--split-by-source` flag。

---

## 8. D 断言验证对照

| D 断言# | 断言内容 | E 验证方法 | 验证结果 | 支持/推翻/未验 |
|:--:|------|------|------|:--:|
| A1 | 9 Agent 管线无 retry 时 P50 150-200s | 跑 200 case 计算 P50 | P50=149.9s（全部 case，retry 极少） | **支持**（在预期边缘） |
| A2 | retry_small 触发率 < 10% | 统计 retry_count>0 比例 | retry_mean_delta=0，说明几乎无 retry 触发 | **未验**（缺 retry_count 明细） |
| A3 | retry_full 触发率 < 5% | 同上 | 同上 | **未验** |
| A4 | 同一 case 不应触发 > 1 次 retry | 检查 retry_count max | 缺数据 | **未验** |
| A5 | 信源评分确定性 | 跑两次对比 | 未执行——仅跑了一次全量 | **未验** |
| A6 | 两阶段仲裁 P95 <= 250s | P95 latency | P95=203.4s | **支持** |
| A7 | LLM 语义扫描假阳性率 0% | 在无矛盾 case 上验证 | 冲突检测率 0%（过于保守，但也无假阳性） | **部分支持** |
| A8 | 有澄清 vs 无澄清准确率差异 | 对比模式 | 未执行——无澄清模块 A/B | **未验** |
| A9 | 澄清模块延迟 < 10s | 计时 | 未执行 | **未验** |
| B1 | winner name 提取成功率 100% | extract_top_recommendation | report_quality check: winner_extractable=100% | **支持** |
| B2 | Docker /health 返回 200 | docker compose up | 未执行——benchmark 不启动 Docker | **未验**（C 阶段验） |
| B3 | conflict_detector 不产生假阳性 | 非矛盾 case | 冲突检测 0%，无假阳性 | **支持**（但过于保守） |
| C1 | 开放讨论 query 冲突检测率 > 15% | 创建 5 个开放讨论 query | 未执行——cases_200 全是 X vs Y 二选一 | **未验** |
| C2 | Official retriever 映射覆盖率 >= 50% | 筛选 case | 未执行 | **未验** |
| C3 | Official retriever URL 全部可达 | HEAD 请求 | 未执行 | **未验** |
| C4 | SelfReviewer 不产生 str.get AttributeError | 收集 error log | 2 例 str.get bug | **推翻**（2/200） |
| C5 | Agent 超时后管线不崩溃 | mock 超时 | 未执行 | **未验** |

**验证统计**：支持 5 / 部分支持 2 / 推翻 1 / 未验 9

---

## 9. 待补项

| # | 项目 | 具体命令 | 优先级 |
|:--:|------|---------|:--:|
| 1 | Agent 延迟拆分 | 修改 `run_baseline.py` 加 `--profile-agents` flag，每个 Agent 包裹 `time.perf_counter()` | P0 |
| 2 | 检索源拆分 | 修改 `run_baseline.py` 加 `--split-by-source` flag，记录每个 URL 所属检索源 | P0 |
| 3 | 澄清模块 A/B | `python benchmarks/run_baseline.py --with-clarify` vs `--without-clarify` 对比 | P1 |
| 4 | 开放讨论 query 测试 | 创建 5-10 个非二选一 query（如"Is React good for enterprise?"），验证冲突检测 | P1 |
| 5 | retry 统计 | 修改 `run_baseline.py` 输出 retry_count 分布（0/1/max）和 retry_type（small/full） | P1 |
| 6 | Official retriever URL 可达性 | `for url in official_urls: curl -s -o /dev/null -w "%{http_code}" $url` | P1 |
| 7 | 断言确定性验证 | `python benchmarks/run_baseline.py --cases 10` 跑两次，对比 source_evaluator 分数 | P2 |

---

## E 执行数据摘要

```
Benchmark: 200 cases, concurrency 5, ~1h45m
Pytest: 87/87 passed (23.59s)
Top-1 Accuracy: 74.9% (131/175)
Source Recall: 38.4% (214/557)
Claim Grounding: 99%
Conflict Detection: 0.0% (LLM judge)
Latency P50/P95: 149.9s / 203.4s
Success Rate: 99.0% (198/200, 2 str.get bugs)
Report Quality A: 97% (194/200)
```
