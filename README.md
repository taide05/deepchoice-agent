# DeepChoice — AI 驱动的技术选型深度研究 Agent

DeepChoice 是一个基于 LangGraph 的多 Agent 研究系统，输入"FastAPI vs Flask 该选哪个"就能自动搜索 6 路数据源、给每篇信源打分、检测矛盾观点并用两阶段仲裁解决、最终输出有据可查的对比推荐报告。

## 为什么值得关注

技术选型搜索通常靠开发者自己翻博客、刷 GitHub、看文档，几个小时下来还不确定信源质量。DeepChoice 把这个过程自动化了——不只是搜，而是评分、对比、仲裁、自审，每一句推荐都能追溯到具体来源。

与 Perplexity/ChatGPT 的对比：它们给答案但不展示证据链和矛盾处理过程。DeepChoice 的输出是**可审计的**——你会看到每篇文章的信源评分、冲突观点是怎么仲裁的、结论为什么可信。

## 核心特性

- **6 路并行检索**：Tavily 网页搜索 + arXiv 论文 + GitHub 仓库 + ChromaDB 本地知识库 + StackExchange 社区 + 官方文档直连（90+ 技术映射），`asyncio.gather` 并发跑，单路挂了不炸全局
- **4 维信源评分**：Authority（官方文档 > 个人博客）、Timeliness（90 天内 > 2 年以上）、Consistency（多源一致 > 孤立观点）、Verifiability（有代码 > 纯观点），规则引擎打分，不靠 LLM 拍脑袋
- **两阶段冲突仲裁**：先让 flash 模型仲裁所有矛盾对（快），再挑出最模糊的一对交给 pro 模型深度重裁（准）。只给一对走 pro，费用可控
- **自审查 + 定向重试**：最后一环用 6 项清单审查报告质量，发现问题自动补搜知识缺口，区分小缺口（重走检索适配）和大缺口（重走全管道）
- **3 种报告格式**：What/Why/How 标准报告、Evidence-First 先给结论再列证据、5 维对比矩阵表。同一份数据，不同输出形式
- **前置澄清模块**：混合式多轮对话，帮用户把"帮我选个框架"这种模糊需求澄清到"团队 5 人、中等复杂度、后端 REST API、关注性能"再开始研究

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
uvicorn src.deepchoice.server.app:app --reload

# 4. 开新终端，启动前端
streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
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
所有冲突对 → deepseek-v4-flash 初裁（~3s/对）
                     │
    低置信度对 → 取分数差距最小的 1 对
                     │
            deepseek-v4-pro 重裁（300s timeout）
```

## 关键技术决策

**信源评分用规则引擎而非 LLM**。Authority/Timeliness/Consistency/Verifiability 四个维度通过 URL 模式匹配、日期计算、关键词检测来评分，结果是确定性的、可复现的。用 LLM 评分会引入幻觉风险——它可能给一篇 CSDN 博客打 9 分。做量化评估的时候，确定性比灵活性更重要。

**冲突检测走嵌入相似度 + LLM 语义扫描**。BGE-M3 先算标题余弦相似度（>= 0.6 的才是潜在冲突对），再用 LLM 语义扫描识别推荐差异、权衡分歧和厂商偏见（而非仅判断"直接事实矛盾"），confirmed 对走两阶段仲裁。100 case 实测，冲突检测率 15.6%——多数技术选型场景无直接矛盾，但存在值得关注的立场差异。

## 量化指标（150 case benchmark，2026-08-06 采集，2026-08-06 V 门禁复核）

| 指标 | 值 | 说明 |
|------|-----|------|
| Top-1 准确率 | **83.2%** | 推荐排名第一的技术匹配人工标注正确答案 |
| 任务成功率 | **100%**（150/150） | 零失败——str.get bug 已根除（`llm.py` 兜底），0 超时 |
| 声明溯源率 | **99.6%** | 几乎每句声明可追溯到具体来源 |
| 信源召回率 | **78.3%** | 90+ 官方文档映射 + 多关键词遍历。较原始 38.4% 翻倍 |
| official_doc 召回率 | **81.9%** | 核心改善——原始仅 20.7%，扩映射表后 4x 提升 |
| 端到端延迟 P50 | **221.7s** | 中位数——约 3.7 分钟完成一次技术选型研究 |
| 端到端延迟 P95 | **281.7s** | 95 分位——扫描限制 15 对 + 证据收集优化 + prompt 缓存 |
| 报告质量 A 级 | **99%** | 5 项确定性质检（不调 LLM），149/150 满分 |

> **数据来源**：以上数字来自 150 case benchmark（200 case 完整集），通过 `benchmarks/run_baseline.py --full --concurrency 8` 采集，每 50 case checkpoint 保存。`report_quality.py` 做确定性质检（非 LLM-as-Judge）。2026-08-06 经 V 门禁全量测试（87/87）+ 一致性核查确认。

```bash
# 重现 100 case benchmark
cd D:\deepchoice-agent
python benchmarks/run_full_200.py          # 200 case 全量（或部分）
python -m benchmarks.run_baseline --merge  # 合并所有批次
```

**分场景准确率**（100 case）：AI/Agent 68% / Backend 65% / Infrastructure **88%** / DevOps 67% / Models 61%。Infrastructure 类（数据库/基础设施选型）最准，Models 类（模型对比）最低——训练数据截止日期影响大。

**已知局限**：端到端延迟较高（P50 265s/P95 420s），主要是矛盾检测、仲裁和证据收集的新增工作——之前这些步骤因检索源问题几乎不产生输出。SelfReviewer 有间歇 `str.get` bug 影响约 3% 成功率（待修复）。conflict_detection_rate 基准 judge 仍偏保守（仅能匹配 14/90 已知矛盾），管道内实际检测到的矛盾数量远高于此。

## 技术栈

LangGraph（9 Agent + checkpoint + 条件路由） · FastAPI + SSE · Streamlit（深色主题 + 4 语言） · DeepSeek API · BGE-M3 嵌入 · ChromaDB · Tavily · GitHub/ArXiv/StackExchange API · Pydantic v2 · pytest

## 项目结构

```
src/deepchoice/
├── agents/          # 9 Agent 节点
├── retrievers/      # 6 路检索器（统一 BaseRetriever 接口）
├── clarify/         # 前置澄清模块
├── formats/         # 3 种报告格式
├── server/          # FastAPI（9 端点 + SSE）
├── state.py         # ResearchState TypedDict
└── utils/           # LLM 客户端 / BGE-M3 嵌入

benchmarks/
├── metrics.py           # 7 指标计算（GSM 框架）
├── run_baseline.py      # 分批 + 合并 + 趋势对比
├── report_quality.py    # 5 项确定性质检（A/B/C/D 评级）
├── cases_200.json       # 200 case benchmark（50 标注 + 150 变体）
├── run_all_batches.ps1  # 分批运行脚本
├── locustfile.py        # 基础并发负载测试
└── annotated_cases.json # 50 手标注 case
```

## License

MIT
