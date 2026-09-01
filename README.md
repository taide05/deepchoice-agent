# DeepChoice — AI 驱动的技术选型深度研究 Agent

DeepChoice 是一个基于 LangGraph 的多 Agent 研究系统，输入"FastAPI vs Flask 该选哪个"就能自动搜索 6 路数据源、给每篇信源打分、检测矛盾观点并用两阶段仲裁解决、最终输出有据可查的对比推荐报告。

## 为什么值得关注

技术选型搜索通常靠开发者自己翻博客、刷 GitHub、看文档，几个小时下来还不确定信源质量。DeepChoice 把这个过程自动化了——不只是搜，而是评分、对比、仲裁、自审，每一句推荐都能追溯到具体来源。

与 Perplexity/ChatGPT 的对比：它们给答案但不展示证据链和矛盾处理过程。DeepChoice 的输出是**可审计的**——你会看到每篇文章的信源评分、冲突观点是怎么仲裁的、结论为什么可信。

## 核心特性

- **6 路并行检索**：Tavily 网页搜索 + arXiv 论文 + GitHub 仓库 + ChromaDB 本地知识库 + StackExchange 社区 + 官方文档直连（222 条：91 种子 + 131 运行时自学习入库），`asyncio.gather` 并发跑，单路挂了不炸全局
- **Tavily 密钥池故障转移**：多 key 轮换，401/432 自动拉黑并持久化到耗尽池（SHA256 哈希状态文件，28 天自动重探），429 限流瞬态退避不误杀，额度耗尽自动切换到仍有额度的 key
- **4 维信源评分**：Authority（官方文档 > 个人博客）、Timeliness（90 天内 > 2 年以上）、Consistency（多源一致 > 孤立观点）、Verifiability（有代码 > 纯观点），规则引擎打分，不靠 LLM 拍脑袋
- **两阶段冲突仲裁**：先让 flash 模型仲裁所有矛盾对（快），再挑出最模糊的一对交给 pro 模型深度重裁（准）。只给一对走 pro，费用可控
- **自审查 + 定向重试**：最后一环用 6 项清单审查报告质量，发现问题自动补搜知识缺口，区分小缺口（重走检索适配）和大缺口（重走全管道）
- **3 种报告格式**：What/Why/How 标准报告、Evidence-First 先给结论再列证据、5 维对比矩阵表。同一份数据，不同输出形式
- **前置澄清模块**：混合式多轮对话，帮用户把"帮我选个框架"这种模糊需求澄清到"团队 5 人、中等复杂度、后端 REST API、关注性能"再开始研究
- **可观测性面板**：运行轨迹时间轴（9 节点瀑布）+ 检索明细（每路延迟/失败）+ 冲突仲裁可视化 + Token 统计（按 Agent/模型聚合），研究过程全程可见
- **报告阅读视图**：目录导航 + 引用角标→证据链卡片联动 + 信源编号，支持 Markdown/PDF 导出

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
pip install -e ".[dev]"

# 2. 配置 API Key
# .env 文件中填入：
#   DEEPSEEK_API_KEY=sk-xxx
#   TAVILY_API_KEY=tvly-xxx
#   GITHUB_TOKEN=ghp_xxx（可选，提升 API 限额）

# 3. 启动后端
uvicorn deepchoice.server.app:app --reload

# 4. 开新终端，启动前端
streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
```

### Docker 部署

```bash
docker build -t deepchoice .
docker run -p 8000:8000 --env-file .env deepchoice
```

镜像构建为纯在线安装（清华镜像源），不依赖本地 wheels 目录。BGE-M3
嵌入模型在容器首次运行时自动下载（约 2GB，下载到 `/root/.cache/huggingface`），
建议挂载 volume 持久化模型缓存：

```bash
docker run -p 8000:8000 --env-file .env \
  -v deepchoice-hf-cache:/root/.cache/huggingface \
  -v deepchoice-outputs:/app/outputs \
  deepchoice
```

## 架构概览

```
用户输入 "FastAPI vs Flask"
        │
        ▼
   ┌──────────────┐
   │  澄清模块      │  多轮对话补齐场景/复杂度/约束（最多 3 轮）
   │  混合式+软门禁  │  用户不知道该选什么 → 按类别推荐候选技术
   └──────┬───────┘
          │ 澄清后的研究任务 + 5 个分解子问题
          ▼
   ┌──────────────────────────────────────────────────────┐
   │              LangGraph 管道（9 Agent）                │
   │                                                      │
   │  [1] QueryAnalyzer      查询分解为 5 维子问题         │
   │         │                                            │
   │  [2] QueryAdapter       每个子问题 → 6 种检索词       │
   │         │                                            │
   │  [3] MultiRetriever     6 路并行搜索                  │
   │         │                                            │
   │  [4] SourceEvaluator    4 维加权评分（规则引擎）       │
   │         │                                            │
   │  [5] ConflictDetector   BGE-M3 检测矛盾 + 两阶段仲裁  │
   │         │                                            │
   │  [6] EvidenceChain      证据链组装 + 强弱标记          │
   │         │                                            │
   │  [7] ConclusionSynth    最终推荐 + 排序 + trade-off   │
   │         │                                            │
   │  [8] ReportGenerator    3 种格式选一渲染               │
   │         │                                            │
   │  [9] SelfReviewer       6 项质量审查                  │
   │         │              confidence < high → retry ──┐  │
   │         ▼                                         │  │
   │       END  ◄──────────────────────────────────────┘  │
   └──────────────────────────────────────────────────────┘
          │
          ▼
   FastAPI SSE 流式输出 → Streamlit 前端（中/英/日/韩）
```

**两阶段仲裁细节**：
```
所有冲突对 → flash 档初裁（~3s/对）
                     │
    低置信度对 → 取分数差距最小的 1 对
                     │
            pro 档重裁（300s timeout）
```

## 关键技术决策

**信源评分用规则引擎而非 LLM**。Authority/Timeliness/Consistency/Verifiability 四个维度通过 URL 模式匹配、日期计算、关键词检测来评分，结果是确定性的、可复现的。用 LLM 评分会引入幻觉风险——它可能给一篇 CSDN 博客打 9 分。做量化评估的时候，确定性比灵活性更重要。

**冲突检测走嵌入相似度 + LLM 语义扫描**。BGE-M3 先算标题余弦相似度（>= 0.6 的才是潜在冲突对），再用 LLM 语义扫描识别推荐差异、权衡分歧和厂商偏见（而非仅判断"直接事实矛盾"），confirmed 对走两阶段仲裁。300 case 终测冲突检测率 28.8%——其中 keyword 预筛部分（确定性）低于 200 case 的 56.4%，主因是新增 case 的 known_contradictions 标注不足（检测靶子少），下一步优化方向是预筛召回而非仲裁质量。

## 量化指标（300 case 混合基准，2026-08-31 终测）

150 对比场景（TC）+ 150 开放场景（OS），覆盖技术选型对比与真实业务需求描述两类输入。300 case 按 TC/OS 交错重排、拆 3 批跑（每批 50 TC + 50 OS），超时/变体补跑后合并。

| 指标 | 值 | 说明 |
|------|-----|------|
| Top-1 准确率 | **92.0%**（287 可判定） | 推荐排名第一的技术匹配人工标注正确答案（13 个 TC 为 context_dependent 标注——无单一正确答案，按设计不计入 Top-1） |
| 任务成功率 | **100%**（300/300） | 零失败——str.get bug 已根除（`llm.py` 兜底）+ 超时补跑 |
| 声明溯源率 | **93.0%** | 精确口径（claim_citation_rate）：每条事实声明带 `[Source: title]` 且 title 真实存在于证据链；**伪造引用 0**（后置校验剔除幻觉引用） |
| 信源召回率 | **66.7%** | official_doc 65.6% / github_repo 73.0% / package_registry 50% / academic+community ~100%（300 case，与 200 case 66.2% 持平） |
| official_doc 召回率 | **65.6%**（346/528） | 官方文档直连 222 条（91 种子 + 131 运行时自学习入库，2026-08-31 种子化） |
| 端到端延迟 P50 | **342.1s** | 中位数——约 5.7 分钟完成一次技术选型研究 |
| 端到端延迟 P95 | **445.3s** | 95 分位——480s 预算内 |
| 报告质量 A 级 | **99%**（297/300） | 5 项确定性质检（不调 LLM） |

> **数据来源**：以上数字来自 300 case 混合基准（`benchmarks/cases_eval_300.json` = 150 TC + 150 OS）。采集分 3 批（`--batch 1/2/3 --batch-size 100`），超时/变体集中补跑（`cases_retry_all.json`）后按 case_id 替换合并。评测覆盖经 3 轮审计修正（case 标注缺陷 T1/T2/T3 修正、OS acceptable 补齐托管维度、变体 query 双场景矛盾清除）。**诚实口径**：Top-1 92.0% 是修正评测覆盖后的真实值——剩余 miss 为真·两难（标注无共识，按设计保留）、模型主流偏差、以及模型真错（详见 case 审计记录）。2026-08-31 终测归档；全量测试 **227 passed + 1 skipped**。

```bash
# 重现 300 case 混合基准（3 批 + 合并）
cd D:\deepchoice-agent
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 1 --batch-size 100 --concurrency 12
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 2 --batch-size 100 --concurrency 12
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 3 --batch-size 100 --concurrency 12
# 合并（自写脚本：runs-batch01/02/03 + 补跑 runs-full 按 case_id 替换，不用内置 merge）
```

**已知局限**：端到端延迟较高（P50 342.1s/P95 445.3s），主要来自矛盾检测、仲裁和证据收集——这是深度研究的代价，480s 预算内。300 case 终测暴露一个信号：**冲突检测率 28.8%**——新增 case 的 known_contradictions 标注不足，预筛召回是杠杆。Tavily 月配额仍是外部约束，但密钥池（多 key 轮换 + 耗尽池持久化 + 28 天自动重探）已把单 key 耗尽从故障降级为吞吐波动。

## 技术栈

LangGraph（9 Agent + checkpoint + 条件路由） · FastAPI + SSE · Streamlit（深色主题 + 4 语言 + 观测面板） · Qwen（DashScope，qwen3.8-flash） · BGE-M3 嵌入 · ChromaDB · Tavily（密钥池） · GitHub/ArXiv/StackExchange API · xhtml2pdf（PDF 导出） · Pydantic v2 · pytest

## 项目结构

```
src/deepchoice/
├── agents/          # 9 Agent 节点
├── retrievers/      # 6 路检索器（统一 BaseRetriever 接口）
├── clarify/         # 前置澄清模块
├── formats/         # 3 种报告格式
├── server/          # FastAPI（16 端点：app.py 12 + clarify_routes 4，含 SSE）
├── state.py         # ResearchState TypedDict
└── utils/           # LLM 客户端 / BGE-M3 嵌入

benchmarks/
├── metrics.py             # 7 指标计算（GSM 框架）
├── run_baseline.py        # 分批 + checkpoint + 趋势对比
├── merge_checkpoints.py   # 中断跑批的 checkpoint 合并工具
├── report_quality.py      # 5 项确定性质检（A/B/C/D 评级）
├── cases_200.json         # 200 对比场景 case（50 标注 + 150 变体）
├── cases_eval_200.json    # 200 混合基准（100 TC + 100 OS）
├── run_all_batches.ps1    # 分批运行脚本
├── locustfile.py          # 基础并发负载测试
└── annotated_cases.json   # 50 手标注 case
```

## License

MIT
