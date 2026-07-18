# DeepChoice — AI 驱动技术选型深度研究

7 Agent 协作的 LangGraph 管道，跨 6 路数据源搜索、信源质量评分、矛盾观点仲裁，生成有据可查的技术对比报告。

## 架构

```
用户查询 → 澄清模块(混合式+软门禁)
              ↓
    7 Agent LangGraph 管道
    ┌─────────────────────────────────────┐
    │ QueryAnalyzer  → MultiRetriever     │
    │   (查询分解)       (6路并行检索)      │
    │        ↓                ↓           │
    │ SourceEvaluator ← ConflictDetector  │
    │   (信源评分)         (矛盾仲裁)       │
    │        ↓                ↓           │
    │ EvidenceChain   → ReportGenerator   │
    │   (证据链组装)       (报告生成)       │
    │        ↓                            │
    │   SelfReviewer → retry/end          │
    │     (自审查+重试)                     │
    └─────────────────────────────────────┘
              ↓
    3 种报告格式 + Streamlit 前端
```

## 快速开始

```bash
# 安装
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
pip install -e ".[dev]"

# 配置环境变量
export DEEPSEEK_API_KEY=sk-xxx
export TAVILY_API_KEY=tvly-xxx

# 启动后端
uvicorn src.deepchoice.server.app:app --reload

# 新终端启动前端
streamlit run frontend/app.py
```

## 技术栈

- **编排**: LangGraph (7 Agent 管道 + checkpoint + conditional routing)
- **检索**: ArXiv / GitHub / Tavily / Chroma KB / Community / Official (6路)
- **后端**: FastAPI + SSE 流式输出
- **前端**: Streamlit (深色主题 + 中/英/日/韩多语言)
- **评估**: 信源评分(规则引擎) + 矛盾仲裁 + 证据链组装 + 自审查

## 项目结构

```
src/deepchoice/
├── agents/          # 7 Agent 节点
├── retrievers/      # 6 路检索器
├── clarify/         # 前置查询澄清模块
├── formats/         # 3 种报告格式
├── server/          # FastAPI 端点
├── state.py         # ResearchState TypedDict
└── utils/           # LLM 封装 / 去重 / 视图
```

## License

MIT
