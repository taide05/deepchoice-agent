# DeepChoice — AI 驱动技术选型深度研究

9 Agent 协作的 LangGraph 管道，跨 6 路数据源搜索、信源质量评分、两阶段矛盾仲裁，生成有据可查的技术对比报告。

## 架构

```
用户查询 → 澄清模块(混合式+软门禁, 最多3轮)
              ↓
        LangGraph 管道 (9 Agent)
    ┌──────────────────────────────────────┐
    │ QueryAnalyzer  →  QueryAdapter       │
    │   (查询分解)       (检索词适配)        │
    │        ↓                ↓            │
    │     MultiRetriever (6路并行)          │
    │        ↓                             │
    │ SourceEvaluator → ConflictDetector   │
    │   (信源评分)       (两阶段仲裁)        │
    │        ↓                ↓            │
    │ EvidenceChain   → ConclusionSynthesizer │
    │   (证据链组装)       (最终推荐)        │
    │        ↓                             │
    │ ReportGenerator → SelfReviewer        │
    │   (3种报告格式)     (6项质量检查+重试)  │
    └──────────────────────────────────────┘
              ↓
    3 种报告格式 + Streamlit 前端 + FastAPI SSE
```

### 两阶段冲突仲裁

```
所有冲突对 → flash 初裁 (fast, ~3s/pair)
                ↓
    low-confidence 对 → 取分数最接近的 1 对
                ↓
         pro 重裁 (300s timeout)
```

## 快速开始

```bash
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
pip install -e ".[dev]"

# 配置环境变量
export DEEPSEEK_API_KEY=sk-xxx
export TAVILY_API_KEY=tvly-xxx
export GITHUB_TOKEN=ghp_xxx  # 可选, 提升 API 限额

# 启动后端
uvicorn src.deepchoice.server.app:app --reload

# 新终端启动前端
streamlit run frontend/app.py
```

## 量化指标 (50-case baseline)

| 指标 | 值 | 
|------|-----|
| Top-1 推荐准确率 | 56.8% |
| 任务成功率 | 100% |
| 声明溯源率 | 92.9% |
| 端到端延迟 P50 | 107s |
| 延迟 P95 | 187s |
| 信源召回率 | 30.4% |

```bash
# 跑 benchmark
python -m benchmarks.run_baseline --batch 1 --batch-size 10 --verbose
python -m benchmarks.run_baseline --merge
```

## 技术栈

- **编排**: LangGraph (9 Agent + checkpoint + conditional routing + retry)
- **检索**: ArXiv / GitHub / Tavily / Chroma KB / StackExchange+Reddit / PyPI (6路 asyncio.gather)
- **后端**: FastAPI + SSE 流式输出 + 9 端点
- **前端**: Streamlit (深色主题 + 中/英/日/韩多语言)
- **质量**: 信源评分(4维加权规则引擎) + 两阶段冲突仲裁(flash→pro) + 证据链组装 + 自审查+重试
- **评估**: GSM 框架 7 指标 + 50 手标注 case + LLM-as-Judge 5 维评分

## 项目结构

```
src/deepchoice/
├── agents/          # 9 Agent 节点 (含两阶段仲裁)
├── retrievers/      # 6 路检索器 (统一 BaseRetriever)
├── clarify/         # 前置查询澄清模块
├── formats/         # 3 种报告格式 (What/Why/How, Evidence-First, Comparison Matrix)
├── server/          # FastAPI 端点
├── state.py         # ResearchState TypedDict
└── utils/           # LLM 封装 / BGE-M3 嵌入 / 日志

benchmarks/
├── metrics.py              # 7 指标计算引擎 (GSM 框架)
├── run_baseline.py         # 分批运行 + 合并 + 趋势对比
└── annotated_cases.json    # 50 手标注技术选型 case
```

## License

MIT
