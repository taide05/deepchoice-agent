# 导读 03：Agent 管道（中）—— 冲突检测 → 证据链

## 覆盖文件
- `src/deepchoice/agents/conflict_detector.py` (140行)
- `src/deepchoice/agents/evidence_chain.py` (53行)

## 模块概述

这两个 Agent 是管道的**质量把关层**——找到互相矛盾的来源，仲裁谁更可信，然后把所有有效结论组织成"证据链"。

```
SourceEvaluator 输出 → ConflictDetector (找矛盾 → LLM仲裁)
                     → EvidenceChain (按强度分级 → 标记争议)
```

---

## 一、conflict_detector.py — 冲突检测与仲裁

### 配置与模型加载

```python
import numpy as np
from sentence_transformers import SentenceTransformer
from ..utils.llm import call_model

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model
```

**为什么用全局变量 + 懒加载？** SentenceTransformer 加载模型需要 1-2 秒、~2GB 内存。如果每次创建 ConflictDetectorAgent 都加载一次，LangGraph pipeline 初始化时 7 个 Agent 各加载一次 → 14GB 内存。全局单例保证整个进程只加载一次。

### 否定词集合

```python
NEGATION_WORDS = {
    # 显式否定
    "not", "no", "never", "fail", "worse", "slow", "bad", "broken", "cannot",
    "doesn't", "don't", "isn't", "won't", "without", "lack", "lacks", "missing",
    # 隐式对比/转折
    "better than", "outperforms", "superior", "inferior", "however",
    "but", "although", "unlike", "versus", "vs", "contrary", "disagree",
    "instead", "rather than", "prefer", "drawback", "downside",
}
```

这组词的目的：**判断两条标题相似的搜索结果是否持不同立场。**

例如：
- 标题 A: "React is better than Vue for large projects"
- 标题 B: "Vue outperforms React in large-scale applications"

两条标题都关于"大型项目中的框架比较"（余弦相似度高），但包含相反的否定/对比词 → 标记为潜在冲突。

### find_contradictions — 冲突发现

```python
def find_contradictions(source_scores: list[dict], threshold: float = 0.6) -> list[dict]:
    model = _get_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    # 批量编码所有标题
    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = model.encode(titles)  # shape: (n, 1024)
    norms = np.linalg.norm(embeddings, axis=1)

    pairs = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            # 余弦相似度 = dot(A,B) / (|A| * |B|)
            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))

            if sim >= threshold:  # 标题相似 → 可能讨论同一话题
                neg_a = any(w in titles[i].lower() for w in NEGATION_WORDS)
                neg_b = any(w in titles[j].lower() for w in NEGATION_WORDS)
                if neg_a != neg_b:  # 一个肯定一个否定 → 冲突
                    pairs.append({
                        "source_a": high_score_sources[i],
                        "source_b": high_score_sources[j],
                        "similarity": round(sim, 3),
                    })
    return pairs
```

### 算法解读

**Step 1: 过滤低分源** — 只处理 total_score >= 5.0 的结果。评分太低的来源不值得花 LLM token 去仲裁。

**Step 2: 批量编码** — 一次性把所有标题转成向量（bge-m3, 1024维），而不是在双层循环里逐对编码。这是**性能优化**：n 条结果，逐对编码需要 O(n^2) 次模型调用，批量编码只需 1 次。

**Step 3: 余弦相似度** — 公式 `cos(A,B) = A·B / (|A| × |B|)`，值域 [-1, 1]。本文件阈值 0.6——标题含义相近（讨论同一话题）。

**Step 4: 否定词检测** — 两条标题都命中"对比"话题（相似度 >= 0.6）但否定词模式不同（一个含否定一个不含，或含不同方向的对比词）→ 判定为冲突。

### 设计决策：为什么用 bge-m3 本地模型而不是调 LLM 做相似度判断？

| 方式 | 一对标题 | 15 条结果（105 对） |
|------|---------|-------------------|
| bge-m3 本地编码 + numpy | ~5ms | ~50ms（批量编码） |
| 调 LLM 判断 | ~300ms | ~31,500ms（31秒） |

105 对全调 LLM 是不可接受的延迟。bge-m3 做"标题语义相似度"足够好——它是一个双塔模型，专门为语义搜索优化的。

### LLM 仲裁

```python
ARBITRATION_PROMPT = """You are an impartial technical arbitrator.

## Source A (score: {score_a}/10, authority: {authority_a}, evidence: {evidence_a})
Claim: {claim_a}

## Source B (score: {score_b}/10, authority: {authority_b}, evidence: {evidence_b})
Claim: {claim_b}

## Rules
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

Return JSON:
{{"resolution": "A_correct|B_correct|both_partial|insufficient_data",
  "confidence": "high|medium|low", "reasoning": "...", "key_factor": "..."}}"""
```

**设计决策：仲裁规则里"分数差 >= 2.5"这个阈值怎么来的？**

不是精确计算，是经验阈值。SourceEvaluator 的 10 分制中，2.5 分约等于一个维度的差距（比如权威性从 blog(7) 降到 reddit(4) = 3 分差距）。这个阈值的效果是：如果两方分数接近（差 < 2.5），不靠分数决定，靠证据类型（code > benchmark > citation > opinion）。

### conflict_detector 的 run 方法

```python
class ConflictDetectorAgent:
    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        pairs = find_contradictions(source_scores)
        if not pairs:
            return {"conflicts": []}  # 无冲突，跳过 LLM 调用

        conflicts = []
        for pair in pairs:
            # 对每对冲突调 LLM 仲裁
            result = await call_model(prompt, model="deepseek-v4-pro", response_format="json")
            conflicts.append({
                "claim_a": ..., "claim_b": ...,
                "resolution": result.get("resolution", "insufficient_data"),
                "confidence": result.get("confidence", "low"),
                ...
            })
        return {"conflicts": conflicts}
```

**注意：这里用的是 `deepseek-v4-pro` 而不是 `deepseek-v4-flash`。** 仲裁需要推理能力（判断两边证据强弱、识别部分正确的情况），pro 模型更合适。

**模型选择原则：错误成本决定模型级别。**

| 节点 | 模型 | 如果出错 | 影响范围 | 有无缓冲 |
|------|------|---------|---------|---------|
| QueryAnalyzer | flash | 子问题偏 | 搜索偏 → 下游稀释 | 有（MultiRetriever 兜底 + SelfReviewer 审查） |
| SourceEvaluator | 规则 | 评分偏 | 排名偏 → 好来源排后面 | 有（ConflictDetector + SelfReviewer） |
| ConflictDetector 仲裁 | **pro** | 判错 | **用户直接看到错误结论** | **无缓冲** |
| SelfReviewer | flash | 置信度偏 | 可能多一次重试 | 有（retry_count 上限） |
| ReportGenerator | 规则 | 格式错 | 报告不好看 | 有（用户自己能判断） |

**仲裁判错了 = 报告直接说"A 对 B 错"→ 用户拿错误结论做技术选型 → 这是最贵的错误。** 所以这里用最强的模型。预处理用便宜模型，终判用贵模型——这在整个管道中是一致的。

### 盲区补课：精度（Precision）vs 召回（Recall）

ConflictDetector 选择了**高精度、低召回**策略。这是什么意思？

| 策略 | 行为 | 结果 |
|------|------|------|
| 高召回 | 降低阈值，多抓配对 | 不遗漏冲突，但很多误报（无关标题也被配对） |
| 高精度 | 提高阈值，少抓配对 | 每个配对大概率真冲突，但可能遗漏（漏判） |

当前策略是**高精度**——阈值 0.6 + 否定词双重过滤。这意味着：
- 报出来的冲突大概率是真的（精度高）
- 但可能漏掉一些用隐晦方式表达的冲突（召回低）

**为什么选高精度不选高召回？** 因为每对"假冲突"都会调一次 pro 模型仲裁——浪费 token 和延迟。漏判的代价是"报告里少标一个争议"，SelfReviewer 的 checklist 第 4 项会再扫一遍。

面试可以这样说：**"冲突检测阶段宁愿漏判不多判——因为每个多判都要花 pro 模型的 token。漏掉的在 SelfReviewer 阶段有二次检查。"**

### 仲裁的串行→并行优化（当前未实现，面试加分项）

当前代码用 `for pair in pairs` 串行调 LLM——3 对冲突 = 3 × 1s = 3s。优化方向：

```python
# 当前：串行
for pair in pairs:
    result = await call_model(...)  # 一个一个等

# 优化：并行
import asyncio
tasks = [call_model(...) for pair in pairs]
results = await asyncio.gather(*tasks)  # 一起等，最慢的决定总时间
```

和 MultiRetriever 的 6 路并行搜索同一模式——**无依赖的 LLM 调用可以并行，总耗时 = max(每次耗时)，不是 sum(每次耗时)。**

### 盲区补课：余弦相似度

公式：`cos(A,B) = (A·B) / (|A| × |B|)`

```
A = [0.1, 0.3, 0.5]     B = [0.2, 0.3, 0.4]
点积 = 0.1×0.2 + 0.3×0.3 + 0.5×0.4 = 0.02 + 0.09 + 0.20 = 0.31
|A| = sqrt(0.01 + 0.09 + 0.25) = sqrt(0.35) = 0.592
|B| = sqrt(0.04 + 0.09 + 0.16) = sqrt(0.29) = 0.538
cos = 0.31 / (0.592 × 0.538) = 0.31 / 0.319 = 0.972
```

值域 [-1, 1]：1 = 方向完全相同，0 = 正交（无关），-1 = 方向完全相反。

**为什么用余弦不用欧氏距离？** 文本向量的绝对长度受文本长度影响（长文本向量值更大），余弦只看方向不看长度，消除了长度偏差。

---

## 二、evidence_chain.py — 证据链构建

### 完整代码

```python
def build_evidence_chain(source_scores: list[dict], conflicts: list[dict]) -> list[dict]:
    # Step 1: 收集有争议的 URL
    disputed_urls = set()
    for c in conflicts:
        disputed_urls.add(c.get("source_a", {}).get("url", ""))
        disputed_urls.add(c.get("source_b", {}).get("url", ""))

    # Step 2: 过滤 + 分级
    chains = []
    for s in source_scores:
        if s["total_score"] < 4.0:
            continue  # 丢弃低分源

        # 三级证据强度
        if s["total_score"] >= 8.0 and len(s.get("supporting_sources", [])) >= 1:
            strength = "strong"
        elif s["total_score"] >= 6.0:
            strength = "moderate"
        else:
            strength = "weak"

        disputed = s["url"] in disputed_urls
        chains.append({
            "conclusion": s.get("title", "Key finding"),
            "sources": [{"url": s["url"], "title": s.get("title", ""),
                         "snippet": s.get("snippet", ""), "score": s["total_score"]}],
            "evidence_strength": strength,
            "disputed": disputed,
        })
    return chains


class EvidenceChainAgent:
    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        conflicts = research_state.get("conflicts", [])
        chains = build_evidence_chain(source_scores, conflicts)
        return {"evidence_chains": chains}
```

### 设计决策

**1. 为什么 EvidenceChain 是纯函数而不是 LLM Agent？**

证据链是**数据重组**——把 SourceEvaluator 的评分和 ConflictDetector 的冲突标记合并成结构化记录。不涉及任何自然语言理解或生成。纯函数比 LLM 快几个数量级，且结果可复现。

**2. 证据强度三级分法的逻辑：**

| 级别 | 条件 | 含义 |
|------|------|------|
| strong | score >= 8.0 + 至少 1 个同伴 | 高分 + 交叉验证 → 高度可信 |
| moderate | score >= 6.0 | 中等分数，可能无误也可能不足 |
| weak | score 4.0-5.9 | 刚好过线，需谨慎对待 |
| 丢弃 | score < 4.0 | 不可信，不进入最终报告 |

**为什么 strong 要求两个条件同时满足（>= 8.0 且 >= 1 同伴），而不是满足一个就行？**

考虑两种边缘情况：

| 情况 | score | 同伴 | 按"或"逻辑 | 按"且"逻辑（当前） | 哪个对？ |
|------|-------|------|----------|------------------|---------|
| 冷门高质量来源 | 8.5 | 0 个 | strong | **moderate** | 当前对——冷门领域高分但没有独立验证，不应标 strong |
| 多个一般来源互相佐证 | 6.5 | 3 个 | strong | **moderate** | 当前对——来源质量一般，互相佐证也只是一般来源互证 |

**分数和一致性缺一不可。** 高分无同伴 = 可能是孤证（即使来源权威），有同伴但低分 = 同伴也是低质量来源。两条件同时满足，strong 才有意义。这是 SourceEvaluator 评分体系的自然延伸，不是独立规则。

**3. disputed 标记的作用：**

被 ConflictDetector 标记的来源，在 ReportGenerator 里会标注 "[争议]"。用户看到争议标记后可以自行判断，而不是被告知一个"确定的"结论。

**4. 为什么在 build_evidence_chain 入口过滤（< 4.0 跳过），而不是在 ReportGenerator 渲染时过滤？**

这是**数据管道原则：在数据源头过滤，不在消费端过滤。** 在入口过滤 = 后续所有环节（evidence_chains → report_generator → self_reviewer）都只处理有效数据，不浪费内存和计算。在渲染器过滤 = 数据传了一圈，最后一步才丢弃——所有中间环节都白白处理了噪音。

面试可以说：**"数据质量门禁放在最靠近数据入口的地方，减少下游数据量。这和多层建筑的垃圾在底层分类不在顶楼分类是一个道理。"**

**4. EvidenceChainAgent 自己没有 async 操作，为什么 run 是 async？**

接口一致性。所有 Agent 的 `run()` 都是 async，LangGraph 统一 `await agent.run(state)`。如果某个 Agent 的 run 是同步的，LangGraph 执行时没有区别——Python 的 `await` 一个同步函数返回的值也能正常工作。但如果未来 EvidenceChain 需要调 LLM（比如自动摘要每条结论），改成 async 不需要改接口。

---

## 面试拷打

### Q1: 为什么冲突检测用 bge-m3 本地模型，而仲裁用 LLM？
分工不同。检测是"找哪两条标题在讨论同一个话题"——语义相似度，bge-m3 专为此设计，快且便宜。仲裁是"判断两方谁对"——需要理解证据强弱、识别部分正确，这需要推理能力，LLM 更合适。

### Q2: 0.6 的相似度阈值怎么定的？
经验值，平衡"不遗漏冲突"和"不把无关标题强行配对"。太高（0.9+）只抓到几乎一样的标题，错过用不同措辞表达相反观点的；太低（0.4-）把无关标题也配对了，浪费 LLM token。

### Q3: 如果相似度高但否定词检测漏了（比如新形式的否定），会发生什么？
两条矛盾的观点被当作"讨论同一话题的不同方面"，没有进入仲裁 → 报告中可能出现未标记的冲突。这是启发式方法的固有限制——NEGATION_WORDS 集合不可能穷举所有否定表达。缓解方式：SelfReviewer 在最终审查时会检查"是否还有未标记的冲突"。

### Q4: EvidenceChain 为什么不是 Agent？
纯数据转换不需要 LLM。"Agent"这个词在这个项目中更多是"管道节点"的意思，不代表一定调 LLM。面试时区分清楚：SourceEvaluator 用规则引擎也不用 LLM，但仍然是管道中的一个 Agent 节点。
