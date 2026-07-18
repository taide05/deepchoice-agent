# 导读 02：Agent 管道（上）—— 查询分析 → 多路检索 → 信源评估

## 覆盖文件
- `src/deepchoice/agents/query_analyzer.py` (63行)
- `src/deepchoice/agents/multi_retriever.py` (61行)
- `src/deepchoice/agents/source_evaluator.py` (164行)

## 模块概述

这三个 Agent 构成 DeepChoice 管道的**前半段**——把用户的模糊问题变成结构化数据：

```
用户 query → QueryAnalyzer (拆解成5维子问题)
           → MultiRetriever (6路并行搜索)
           → SourceEvaluator (逐条打分 + 交叉互验 + 排名)
```

---

## 一、query_analyzer.py — 问题分解

### 完整代码

```python
from ..utils.llm import call_model
from ..utils.views import print_agent_output

DECOMPOSITION_PROMPT = """You are a technical research analyst. Decompose the user's
technology selection question into 5 analysis dimensions.

User query: {query}
User context: {scene_context}
Known constraints: {constraints}

For EACH of these 5 dimensions, generate 1-2 specific sub-questions:
1. 功能 (Functionality): Feature coverage, API completeness, capability fit
2. 性能 (Performance): Throughput, latency, resource consumption
3. 生态 (Ecosystem): Community activity, plugins/extensions, documentation quality
4. 体验 (Developer Experience): Learning curve, debugging difficulty, productivity
5. 场景 (Scenario Fit): Applicability boundaries, anti-patterns, context match

CRITICAL: Each sub-question MUST include:
- At least one concrete technology/framework name from the user's query
- A specific metric or comparison point
- Minimum 15 Chinese characters or 10 English words
- NO generic "Compare X and Y" questions

Scene context detection:
- "solo": solo developer (1-5 people) — prioritize simplicity, learning curve, cost
- "team": mid-size team (20-100 people) — prioritize reliability, ecosystem, team productivity
- "enterprise": large org (500+ people) — prioritize compliance, SLA, security, scalability

Return ONLY a JSON object:
{{"sub_questions": ["q1", "q2", "..."], "scene_context": "solo|team|enterprise",
  "constraints": ["c1", "c2", "..."]}}"""


class QueryAnalyzerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        task = research_state["task"]
        prompt = [{
            "role": "user",
            "content": DECOMPOSITION_PROMPT.format(
                query=task["query"],
                scene_context=task.get("scene_context", "unspecified"),
                constraints=", ".join(task.get("constraints", [])) or "none",
            ),
        }]
        result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
        return {
            "sub_questions": result.get("sub_questions", []),
            "scene_context": result.get("scene_context", task.get("scene_context", "team")),
            "constraints": result.get("constraints", task.get("constraints", [])),
        }
```

### 分段解读

**Prompt 设计的三个层次：**

| 层次 | 在 Prompt 中的体现 | 作用 |
|------|-------------------|------|
| 角色定义 | "You are a technical research analyst" | 设定模型行为框架 |
| 输出结构约束 | 五个维度 + CRITICAL 规则 + JSON 格式 | 控制输出质量和格式 |
| 场景自适应 | solo/team/enterprise 三档加权 | 让同一个 prompt 适应不同用户 |

**CRITICAL 段的意图：** 防止 LLM 偷懒返回泛问题。比如不写这行，模型可能返回 `"compare React and Vue performance"`——太泛，搜不出有效结果。加了以后会更可能返回 `"React useMemo vs Vue computed property re-computation trigger benchmark 2025"`。

### 设计决策

**1. 为什么先分解再搜索，而不是直接搜原始 query？**

直接搜"React vs Vue"——结果全是泛泛的博客对比，没有深度。分解后再搜"React useState vs Vue ref reactivity performance benchmark"——结果精准得多。**搜索质量取决于搜索词的质量**，这是整个管道最重要的前提。

**2. 为什么选这五个维度？**

这是技术选型的通用框架，覆盖了决策需要的全部视角。面试时如果被问"为什么是这五个"，回答："功能、性能、生态是硬指标，开发体验和场景适配是软指标，五维覆盖了技术选型决策树的所有分支。"

**3. 为什么用 deepseek-v4-flash 而不是 v4-pro？**

分解任务是"翻译"——把一个问题展开成五个子问题，不需要深度推理。flash 模型更快更便宜，pro 留给下游 ConflictDetector 的仲裁（那是真正需要推理的）。

**4. LLM vs 规则的选择边界——什么时候调 LLM，什么时候用规则？**

这是全项目最重要的工程判断。判断标准就一条：**输入是否涉及自然语言理解？**

| 场景 | 输入 | 是否需语义理解 | 用？ |
|------|------|-------------|------|
| QueryAnalyzer | "React vs Vue 哪个好" | 需理解"哪个好"=比较 | LLM |
| SourceEvaluator | URL + snippet | arxiv 永远是 arxiv | 规则 |
| ConflictDetector 检测 | 标题文本 | 看相似度+否定词 | 规则 |
| ConflictDetector 仲裁 | 两方论断 | 需理解技术上下文 | LLM |
| EvidenceChain | 已有分数+标签 | 纯数据转译 | 规则 |

面试被问"你为什么有些地方用 LLM 有些不用"——直接画这个表。核心原则：**LLM 用于需要语义理解的环节，规则用于可穷举的分类/计算环节。** 同一模块内也可以混合（ConflictDetector: 规则检测 + LLM 仲裁）。

**5. 场景（solo/team/enterprise）为什么不是并列维度，而是权重的来源？**

五维（功能/性能/生态/体验/场景）是分析框架，场景三档（solo/team/enterprise）是**分析框架的加权方式**。同样的技术、同样的问题，solo 优先学习曲线和成本，enterprise 优先合规和 SLA。这和 SourceEvaluator 的 WEIGHTS 字典是同一设计模式：把"评什么"和"怎么加权"分开。区别在于 SourceEvaluator 权重写死在代码里，QueryAnalyzer 权重从场景推断——更灵活但依赖 LLM。

**6. 为什么场景分三档，不是更细粒度（5人/20人/100人/500人）？**

三档是粗粒度意图分类。15 人创业公司归 team 档即可——不需要精确到人数。而且分类逻辑写在 Prompt 里（solo/team/enterprise 的定义），未来加一档只改 Prompt 文本不用改代码。这是 LLM 应用常见模式：**分类逻辑放 Prompt，代码只管调用+解析。**

### 盲区补课：Garbage In, Gospel Out 链路

这是这个模块最危险的故障模式：

```
废子问题（QueryAnalyzer 分解失败）
  → 6路重复检索（用泛词搜，结果雷同）
    → SourceEvaluator 交叉互验（相似结果互相"验证"，consistency 虚高）
      → 全部高分 → 报告虚假信心（confidence: high，但内容空洞）
```

这个链路叫 **Garbage In, Gospel Out**——输入是垃圾，但管道把它层层加工成了"看起来可信"的结果。三层防御：
1. QueryAnalyzer 的 CRITICAL 段（防止 LLM 偷懒产废子问题）
2. MultiRetriever 的 `_is_too_generic` 门禁（拦截明显太泛的子问题）
3. SelfReviewer 的 checklist 第 5 项（"子问题全回答了吗？"）

这三层任何一层失效，后面两层兜底。

### 盲区补课：Prompt 中的 Scene Context 三段式

```
solo:   "prioritize simplicity, learning curve, cost"
team:   "prioritize reliability, ecosystem, team productivity"
enterprise: "prioritize compliance, SLA, security, scalability"
```

这三个关键词组合不是随便写的——它们对应三个场景的**核心约束**：
- 个人：时间少、钱少、一个人能搞定 → 简单 > 强大
- 团队：人多、需要协作、出问题影响面大 → 可靠 > 简单
- 企业：合规要求、SLA 承诺、安全审计 → 合规 > 效率

面试追问"你怎么知道 solo 应该 prioritize simplicity"——答：这是业务判断，不是技术判断。Prompt 工程的核心能力是**把业务需求翻译成 LLM 能执行的指令**。

---

## 二、multi_retriever.py — 并行调度

### 完整代码

```python
import asyncio
from ..retrievers import RETRIEVER_REGISTRY
from ..utils.views import print_agent_output


def _is_too_generic(sub_questions: list[str], query: str) -> bool:
    if not sub_questions:
        return True
    avg_len = sum(len(q) for q in sub_questions) / len(sub_questions)
    return avg_len < 20


def _supplement_sub_questions(sub_questions: list[str], query: str) -> list[str]:
    return [f"{query} — detailed technical comparison"] + sub_questions


class MultiRetrieverAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        query = research_state["task"]["query"]
        sub_questions = research_state.get("sub_questions", [])

        if _is_too_generic(sub_questions, query):
            sub_questions = _supplement_sub_questions(sub_questions, query)

        tasks = []
        for name, cls in RETRIEVER_REGISTRY.items():
            retriever = cls()
            tasks.append(retriever.search(query, sub_questions))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        search_results = []
        partial_failures = []
        for name, result in zip(RETRIEVER_REGISTRY.keys(), raw_results):
            if isinstance(result, Exception):
                search_results.append({
                    "source": name, "status": "failed",
                    "results": [], "error": str(result), "latency_ms": 0,
                })
                partial_failures.append(name)
            else:
                search_results.append(result)
                if result["status"] == "failed":
                    partial_failures.append(name)

        return {"search_results": search_results, "partial_failures": partial_failures}
```

### 设计决策

**1. 为什么用 asyncio.gather 而不是 asyncio.wait？**

`gather` 保持顺序——返回结果顺序和传入 task 顺序一致，所以 `zip(RETRIEVER_REGISTRY.keys(), raw_results)` 能正确配对检索器名称和结果。`wait` 返回的是 `(done, pending)` 两个 set，无序，需要额外的名称追踪逻辑。

**2. 为什么用 `return_exceptions=True`？**

不加这个参数：6 路检索器，任一路抛异常 → gather 立即抛异常 → 其他 5 路被取消 → 全失败。加了以后：异常不传播，变成返回值里的 Exception 对象，其余 5 路正常获得结果。

这是**部分失败容错（Partial Failure Tolerance）**——调用外部服务时必须考虑的工程原则。

**3. 两层失败检查的区别：**

```python
# 第一层：Python 进程级失败
if isinstance(result, Exception):      # 网络超时、DNS 失败、连接拒绝
    ...

# 第二层：应用级失败
if result["status"] == "failed":       # API key 过期、限流、搜索词不支持
    ...
```

第一层是"根本没通"，第二层是"通了但对方返回了失败状态"。两层覆盖了检索器所有可能的失败方式。

**4. `_is_too_generic` 的阈值 20 为什么不需要精确？**

这个函数的代价是**误判放行**（一个泛问题没被拦截）而不是**漏判拦截**（一个好问题被误杀）。放行的代价极小——最多多搜一个泛关键词。这个设计遵循 **fail open 原则**：不确定的时候宁可多做（多搜）不要少做（漏搜）。

**5. 为什么 supplement 加在最前面而不是最后面？**

```python
# 放前面
[f"{query} — detailed technical comparison"] + sub_questions
# 结果: ["React vs Vue — detailed ...", "泛词1", "泛词2", ...]
```

处理顺序 = 优先级。最可靠的关键词放第一位，确保至少第一个搜索词能拿到有效结果。泛词放后面碰运气。

**6. partial_failures 目前只被 ReportGenerator 消费——那现在算"预留数据通道"还是"死代码"？**

| | 预留数据通道 | 死代码 |
|------|------------|--------|
| 有消费者吗？ | 有（下游某处会读） | 没有 |
| 不写会怎样？ | 消费者拿不到数据，功能降级 | 什么都不影响 |
| 该删吗？ | 不删，等待消费者接入 | 该删 |

partial_failures 是预留数据通道——ReportGenerator 已经在消费它生成数据覆盖声明。Orchestrator 未来可以在报告头标注"本次 X 路不可用"，排查"为什么这次结论不准"时也有线索。区别在于：**预留数据通道有明确的未来消费方和场景，死代码是从未设计过消费者。**

---

## 三、source_evaluator.py — 信源评估

### 配置表

```python
WEIGHTS = {
    "authority": 0.35,    # 权威性权重最高
    "timeliness": 0.25,
    "consistency": 0.20,
    "verifiability": 0.20,
}

AUTHORITY_MAP = {
    "official_doc": 10, "arxiv_paper": 10,
    "tech_blog": 7, "github": 6,
    "stackoverflow": 5, "reddit": 4, "anonymous": 2,
}

VERIFIABILITY_MAP = {
    "code": 10, "benchmark": 8, "citation": 6, "opinion": 2,
}
```

### 源类型分类（classify_source_type）

```python
def classify_source_type(url: str, source: str) -> str:
    url_lower = url.lower()
    if "arxiv.org" in url_lower:        return "arxiv_paper"
    if "github.com" in url_lower:       return "github"
    if "stackoverflow.com" in url_lower: return "stackoverflow"
    if "reddit.com" in url_lower:       return "reddit"
    if source == "official" or "readthedocs" in url_lower or "docs." in url_lower:
        return "official_doc"
    if "blog" in url_lower or "medium.com" in url_lower or "dev.to" in url_lower:
        return "tech_blog"
    return "tech_blog"  # 默认 fallback
```

**关键设计：if-elif 的顺序就是优先级。** `arxiv.org` 优先于 `blog`，因为一个 URL 不可能同时是两者。顺序错了可能导致误分类。

### 证据类型分类（classify_evidence_type）

```python
def classify_evidence_type(snippet: str) -> str:
    snip_lower = snippet.lower()
    if any(kw in snip_lower for kw in ["```", "def ", "import ", "pip install"]):
        return "code"
    if any(kw in snip_lower for kw in ["benchmark", "throughput", "latency"]):
        return "benchmark"
    ...
    return "citation"  # 默认 fallback
```

**默认 fallback 选 "citation"(6分) 而不是 "opinion"(2分)。** 这和前面的 `_is_too_generic` 一样是 fail open——不确定的时候假设它有一定价值，下游还有机会纠正。

### 评分函数（四个维度）

```python
def score_authority(source_type: str) -> int:
    return AUTHORITY_MAP.get(source_type, 4)  # 未知类型默认 4 分

def score_timeliness(date_str: str | None) -> int:
    if not date_str:
        return 5
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    age = (datetime.now() - d).days
    if age < 90: return 10      # 3个月内
    if age < 180: return 8      # 半年内
    if age < 365: return 6      # 一年内
    if age < 730: return 4      # 两年内
    return 2

def score_consistency(supporting_sources: list[str], has_contradiction=False) -> int:
    if has_contradiction: return 2
    if len(supporting_sources) >= 2: return 10   # 2+ 独立来源交叉验证
    if len(supporting_sources) == 1: return 6    # 1 个支持来源
    return 4                                       # 孤证

def score_verifiability(evidence_type: str) -> int:
    return VERIFIABILITY_MAP.get(evidence_type, 4)
```

### ScoreEvaluatorAgent.run() — 两轮评分

```python
class SourceEvaluatorAgent:
    async def run(self, research_state: dict) -> dict:
        # === 第一轮：独立评分 ===
        all_results = []
        for channel in research_state.get("search_results", []):
            source = channel.get("source", "unknown")
            for r in channel.get("results", []):
                all_results.append({**r, "_source": source})

        source_scores = []
        for result in all_results:
            source_type = classify_source_type(result.get("url", ""), ...)
            evidence_type = classify_evidence_type(result.get("snippet", ""))
            scores = {
                "authority": score_authority(source_type),
                "timeliness": score_timeliness(result.get("date")),
                "consistency": score_consistency([url]),  # 第一轮：孤证=4分
                "verifiability": score_verifiability(evidence_type),
            }
            total = compute_total_score(scores)
            source_scores.append({...})

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)

        # === 第二轮：交叉互验 ===
        for s in source_scores:
            similar = [
                x["url"] for x in source_scores
                if x["url"] != s["url"] and x["total_score"] >= 6.0
            ]
            s["supporting_sources"] = similar[:3]
            s["scores"]["consistency"] = score_consistency(similar)
            s["total_score"] = compute_total_score(s["scores"])

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)
        return {"source_scores": source_scores}
```

### 设计决策

**1. 为什么用规则引擎而不是 LLM 打分？**

| 维度 | 规则引擎 | LLM 打分 |
|------|---------|---------|
| 速度 | 即时（查表） | 每条 0.5-1s |
| 成本 | 0 | 每条 ~50 tokens |
| 可解释性 | 精确到每个维度 | "综合判断" |
| 可复现性 | 同一输入→同一输出 | 温度 0 也可能微调 |

30-60 条结果全调 LLM 又慢又贵。信源评估不需要深层语义——arxiv 就是比 reddit 权威，这是常识不是推理。

**2. 为什么分两轮评分？**

第一轮每条独立评，consistency 全是 4 分（孤证）。第二轮互验：每条找 >= 6.0 分的其他来源作佐证，有 2+ 同伴的 consistency 从 4 → 10。互验反映"这条结论有没有其他独立来源背书"。

**3. 为什么默认 fallback 选 tech_blog(7分) 不选 anonymous(2分)？**

Fail open。误杀一个好来源（漏掉关键信息）比放行一个垃圾来源（多一条噪音）代价大。下游 ConflictDetector + SelfReviewer 还有纠正机会。`AUTHORITY_MAP.get(source_type, 4)` 是第二层兜底。

**4. WEIGHTS 为什么加起来 = 1.0？**

这叫**归一化权重**。好处是总分始终在 0-10 范围内，不同批次的结果可比较。不需要归一化也能做排名（只需排序），但归一化后面试官问"这个 7.8 分和那个 6.2 分差多少"你能回答"差 1.6 分，按 10 分制约 16% 的差距"。

### 盲区补课：规则引擎 vs 机器学习

| | 规则引擎 | 机器学习（learning-to-rank） |
|------|---------|---------|
| 冷启动 | 直接可用 | 需要标注数据 |
| 可解释 | 逐维度透明 | 特征重要性可解释但不如规则直观 |
| 维护 | 人工调阈值 | 模型自动学习 |
| 适用场景 | 规则明确、变化慢 | 规则模糊、变化快、有反馈数据 |

这个项目没有用 learning-to-rank 是因为零标注数据——你需要用户点击/选择来训练，冷启动阶段不可能有。

### 盲区补课：SourceEvaluatorAgent.run() 是 async 函数但内部没有任何 await——为什么？

```python
class SourceEvaluatorAgent:
    async def run(self, research_state: dict) -> dict:
        # 全是同步操作：for 循环、字典操作、排序
        # 没有 await 任何东西
        ...
```

这是**接口一致性 > 实际需要**。所有 Agent 的 `run()` 都是 async，因为 LangGraph 统一用 `await agent.run(state)` 调用。如果 SourceEvaluator 的 run 是同步的，LangGraph 调用它也不会报错（Python 的 await 对同步函数返回值也能工作），但接口不统一——未来如果 SourceEvaluator 需要调 LLM（比如自动摘要每条结论），改成 async 需要改接口签名。

面试可以这样说：**"为未来扩展预留了 async 接口。当前纯计算不需要异步，但接口层的成本为零——多写一个 async 关键字不影响性能，需要时省一次重构。"**

---

## 面试拷打

### Q1: QueryAnalyzer 的 Prompt 里 CRITICAL 段如果删掉会怎样？
LLM 倾向于输出最短有效答案（省 token 本能）。没有 CRITICAL 约束，可能返回 `["compare React and Vue functionality", "compare React and Vue performance", ...]`——全是"compare X and Y"模板，搜不出深度内容。

### Q2: MultiRetriever 的 partial_failures 现在谁在消费？
ReportGenerator。它用 partial_failures 生成"数据覆盖声明"——告诉用户"本次结论基于 5/6 路可用数据源，XXX 不可用"。

### Q3: SourceEvaluator 两轮评分后重新排序，第一轮排序是不是多余的？
第一轮排序是为了第二轮"similar"的判断有意义——高分源找同伴，同伴标准是 >= 6.0。如果第一轮不排，所有源的交互相似度都一样（都是孤证 4 分），互验没有区分度。第一轮排完后，高分源互相确认，低分源仍然孤证。

### Q4: 如果用户 query 是中英文混合（"React vs Vue 哪个更适合做后台管理系统"），整个管道哪里会出问题？
- `classify_source_type`: 没问题，只看 URL
- `classify_evidence_type`: snippet 英文关键词可能命中，中文"我认为"不会命中 opinion 检测 → 中文观点被误标为 citation
- QueryAnalyzer: 模型理解中英混合没问题
