import json
from .session_manager import SessionState
from ..utils.llm import call_model

TECH_RECOMMENDATION_MAP: dict[str, list[dict]] = {
    "fc14a2e9": [
        {"name": "React", "stars": "225k+", "desc": "生态最大，招人最容易"},
        {"name": "Vue", "stars": "48k+", "desc": "上手快，中文文档好"},
        {"name": "Angular", "stars": "95k+", "desc": "企业级，TypeScript原生"},
        {"name": "Svelte", "stars": "80k+", "desc": "编译时框架，运行时体积小"},
        {"name": "SolidJS", "stars": "33k+", "desc": "性能极致，React 式语法"},
    ],
    "a7b31d5f": [
        {"name": "FastAPI", "stars": "78k+", "desc": "异步原生，自动API文档"},
        {"name": "Django", "stars": "80k+", "desc": "全栈框架，ORM+Admin开箱即用"},
        {"name": "Flask", "stars": "68k+", "desc": "轻量灵活，插件丰富"},
        {"name": "Spring Boot", "stars": "75k+", "desc": "Java生态，企业级标准"},
        {"name": "Express", "stars": "65k+", "desc": "Node.js 标配，中间件生态"},
        {"name": "Go-Gin", "stars": "79k+", "desc": "高性能，云原生首选"},
    ],
    "b82c4e6a": [
        {"name": "LangChain", "stars": "95k+", "desc": "灵活度最高，生态最大"},
        {"name": "LlamaIndex", "stars": "37k+", "desc": "数据索引强项，RAG首选"},
        {"name": "LangGraph", "stars": "10k+", "desc": "状态图编排，复杂Agent流程"},
        {"name": "Dify", "stars": "55k+", "desc": "低代码平台，上手最快"},
        {"name": "Coze", "stars": "字节跳动", "desc": "国内生态好，飞书集成"},
        {"name": "Semantic Kernel", "stars": "22k+", "desc": "微软官方，C#/Python双语言"},
        {"name": "CrewAI", "stars": "21k+", "desc": "多Agent协作，角色扮演模式"},
        {"name": "AutoGen", "stars": "36k+", "desc": "微软出品，对话式多Agent"},
    ],
    "c93d5f7b": [
        {"name": "Pandas", "stars": "44k+", "desc": "Python数据分析标配"},
        {"name": "Polars", "stars": "31k+", "desc": "Rust内核，比Pandas快10x"},
        {"name": "Streamlit", "stars": "36k+", "desc": "纯Python写数据App"},
        {"name": "Apache Spark", "stars": "40k+", "desc": "大数据分布式处理"},
        {"name": "DuckDB", "stars": "25k+", "desc": "嵌入式OLAP，单机性能强"},
    ],
    "d04e6a8c": [
        {"name": "Flutter", "stars": "167k+", "desc": "Google出品，跨平台性能好"},
        {"name": "React Native", "stars": "119k+", "desc": "React生态，热更新方便"},
        {"name": "UniApp", "stars": "40k+", "desc": "国内主流，小程序兼容"},
        {"name": "SwiftUI", "stars": "仅iOS", "desc": "Apple原生，性能最佳"},
        {"name": "Kotlin Multiplatform", "stars": "16k+", "desc": "跨平台新势力"},
    ],
    "e15f7b9d": [
        {"name": "Docker", "stars": "68k+", "desc": "容器化标准"},
        {"name": "Kubernetes", "stars": "111k+", "desc": "容器编排，云原生标配"},
        {"name": "GitHub Actions", "stars": "免费", "desc": "CI/CD，GitHub集成"},
        {"name": "Vercel", "stars": "免费额度", "desc": "前端部署，Git推送即上线"},
        {"name": "Railway", "stars": "收费", "desc": "全栈部署，比Vercel灵活"},
    ],
}

CATEGORY_KEYWORDS: dict[str, str] = {
    "前端": "fc14a2e9", "网站": "fc14a2e9", "网页": "fc14a2e9", "ui": "fc14a2e9",
    "后台": "a7b31d5f", "后端": "a7b31d5f", "api": "a7b31d5f", "接口": "a7b31d5f", "服务": "a7b31d5f",
    "对话": "b82c4e6a", "聊天": "b82c4e6a", "机器人": "b82c4e6a", "agent": "b82c4e6a", "ai": "b82c4e6a",
    "数据": "c93d5f7b", "分析": "c93d5f7b", "报表": "c93d5f7b", "etl": "c93d5f7b",
    "移动": "d04e6a8c", "app": "d04e6a8c", "手机": "d04e6a8c", "android": "d04e6a8c", "ios": "d04e6a8c",
    "部署": "e15f7b9d", "上线": "e15f7b9d", "运维": "e15f7b9d", "cicd": "e15f7b9d", "容器": "e15f7b9d",
}

CATEGORY_LABELS: dict[str, str] = {
    "fc14a2e9": "前端框架",
    "a7b31d5f": "后端框架",
    "b82c4e6a": "AI/Agent框架",
    "c93d5f7b": "数据处理",
    "d04e6a8c": "移动端框架",
    "e15f7b9d": "部署运维",
}

CLARIFY_SYSTEM_PROMPT = """你是技术选型需求分析师。通过多轮对话，帮用户把模糊的技术选型问题逐步澄清。

## 当前已探明的信息
- 候选技术：{candidate_techs}
- 业务/落地场景：{scene}
- 项目复杂度：{complexity}
- 已知约束：{constraints}
- 用户技术水平：{tech_level}

## 仍需探明的必填项
{missing_required}

## 当前轮次
{clarify_rounds} / 3

## 动作规则

### 1. 有必填缺口 + 轮次 < 3 → action: "ask"
聚焦于优先级最高的缺口（scene > candidate_techs > complexity），问一个具体问题。
- 场景缺口："你这个项目是个人学习/团队协作/还是企业级的？大概几个人用？"
- 候选技术缺口："你有想比较的具体技术吗？还是让我推荐？"
- 复杂度缺口："这个项目的业务逻辑复杂吗？是简单CRUD还是涉及复杂的数据处理/权限/实时通信？"
规则：每次只问一个问题，不要一次问多个维度。

### 2. 候选技术缺失 + 用户不懂技术 → action: "recommend"
此时不要在 message 里写推荐列表（推荐列表由前端卡片渲染），message 字段写引导语。

### 3. 必填项已齐全 → action: "confirm"
输出完整需求摘要。message 字段写摘要文本，语气确认式。

### 4. 轮次 >= 3 且仍有缺口 → 自动补默认值 + confirm
告知用户"以下部分为推测，可以修改"，直接输出需求摘要。

## 输出格式
返回纯 JSON（不要 markdown 代码块包裹）：
{{"action": "ask|recommend|confirm", "message": "...", "scene": null, "complexity": null, "candidate_techs": [], "unknown_techs": false, "constraints": []}}

- message: 给用户看的文本，1-2句话
- 其他字段: 从用户回复中提取的信息（本轮新提取到的），未提取到则填 null 或空列表
"""


def _match_categories(query: str) -> list[str]:
    """Match query keywords to tech categories. Returns list of category IDs."""
    query_lower = query.lower()
    matched = []
    for kw, cat_id in CATEGORY_KEYWORDS.items():
        if kw in query_lower and cat_id not in matched:
            matched.append(cat_id)
    return matched if matched else ["b82c4e6a"]


def _get_recommendations(state: SessionState) -> list[dict]:
    """Query the static recommendation map based on state."""
    user_messages = " ".join([
        m["content"] for m in state.messages if m["role"] == "user"
    ])
    cat_ids = _match_categories(user_messages)
    candidates = []
    seen = set()
    for cat_id in cat_ids[:2]:
        for tech in TECH_RECOMMENDATION_MAP.get(cat_id, []):
            if tech["name"] not in seen:
                candidates.append(tech)
                seen.add(tech["name"])
    return candidates[:7]


class ClarificationAgent:

    async def decide_and_respond(self, state: SessionState) -> dict:
        action = self._decide_action(state)

        if action == "recommend":
            return await self._handle_recommend(state)
        elif action == "confirm":
            return await self._handle_confirm(state)
        else:
            return await self._handle_ask(state)

    def _decide_action(self, state: SessionState) -> str:
        if state.clarify_rounds >= 3:
            return "confirm"

        if not state.missing_required:
            return "confirm"

        if "candidate_techs" in state.missing_required and state.unknown_techs:
            return "recommend"

        return "ask"

    async def _handle_ask(self, state: SessionState) -> dict:
        prompt_text = self._build_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            return self._merge_and_build_response(state, result)
        except Exception:
            return self._fallback_response(state)

    async def _handle_recommend(self, state: SessionState) -> dict:
        candidates = _get_recommendations(state)
        prompt_text = self._build_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            response = self._merge_and_build_response(state, result)
            response["action"] = "recommend"
            response["payload"] = {"candidates": candidates}
            return response
        except Exception:
            return {
                "action": "recommend",
                "answer": "根据你的描述，以下技术可能适合你的场景。你想比较哪几个？可以多选。",
                "payload": {"candidates": candidates},
                "clarity_score": state.clarity_score,
                "filled_required": state.filled_required,
                "missing_required": state.missing_required,
                "clarify_rounds": state.clarify_rounds,
            }

    async def _handle_confirm(self, state: SessionState) -> dict:
        self._apply_defaults(state)
        prompt_text = self._build_confirm_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
        except Exception:
            result = {"message": "需求已整理完毕，确认后开始研究。"}

        state.clarified_task = {
            "query": state.messages[0]["content"] if state.messages else "",
            "scene_context": state.scene,
            "constraints": state.constraints,
            "candidate_techs": state.candidate_techs,
            "complexity": state.complexity,
            "report_format": "what_why_how",
        }

        return {
            "action": "confirm",
            "answer": result.get("message", "需求已整理完毕，确认后开始研究。"),
            "payload": {
                "summary": result.get("message", ""),
                "clarified_task": state.clarified_task,
                "candidate_techs": state.candidate_techs,
                "scene": state.scene,
                "complexity": state.complexity,
            },
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    async def _handle_finalize(self, state: SessionState) -> dict:
        sub_questions = await self._generate_sub_questions(state)
        state.sub_questions = sub_questions
        techs_str = ", ".join(state.candidate_techs) if state.candidate_techs else "推荐技术"
        return {
            "action": "finalize",
            "answer": "需求已确认，开始研究。",
            "payload": {
                "summary": f"需求确认：{state.scene}场景，{state.complexity}复杂度，比较 {techs_str}。",
                "clarified_task": state.clarified_task,
                "sub_questions": sub_questions,
            },
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _build_prompt(self, state: SessionState) -> str:
        return CLARIFY_SYSTEM_PROMPT.format(
            candidate_techs=", ".join(state.candidate_techs) if state.candidate_techs else "未知",
            scene=state.scene or "未知",
            complexity=state.complexity or "未知",
            constraints=", ".join(state.constraints) if state.constraints else "无",
            tech_level="不太懂技术，需要推荐" if state.unknown_techs else "了解技术，有自己的候选",
            missing_required=", ".join(state.missing_required) if state.missing_required else "无（所有必填项已齐全）",
            clarify_rounds=state.clarify_rounds,
        )

    def _build_confirm_prompt(self, state: SessionState) -> str:
        scene_map = {"solo": "个人/学习", "team": "中型团队", "enterprise": "大型企业"}
        complexity_map = {"simple": "简单CRUD", "medium": "中等业务逻辑", "complex": "复杂多系统交互"}
        return f"""你是技术选型需求分析师。所有必填信息已收集完毕，请输出需求确认摘要。

已探明的信息：
- 候选技术：{', '.join(state.candidate_techs) if state.candidate_techs else '待推荐'}
- 业务场景：{state.scene}（{scene_map.get(state.scene, '未知')}）
- 项目复杂度：{state.complexity}（{complexity_map.get(state.complexity, '未知')}）
- 约束条件：{', '.join(state.constraints) if state.constraints else '无特殊约束'}

用户原始需求：{state.messages[0]['content'] if state.messages else ''}

请用1-2句话总结这个需求，让用户确认。语气确认式，结尾问'确认无误就为你开始研究？'。

返回JSON：{{"message": "你的需求摘要..."}}"""

    async def _generate_sub_questions(self, state: SessionState) -> list[str]:
        techs = ", ".join(state.candidate_techs) if state.candidate_techs else "推荐技术"
        prompt_text = f"""你是技术研究分析师。基于以下已澄清的需求，生成5个研究子问题，覆盖5个维度：功能、性能、生态、开发体验、场景适配。

需求：
- 候选技术：{techs}
- 场景：{state.scene}（solo=个人/team=团队/enterprise=企业）
- 复杂度：{state.complexity}

每个维度生成1个具体的、可检索的子问题。返回JSON：{{"sub_questions": ["q1", "q2", "q3", "q4", "q5"]}}"""

        prompt = [{"role": "user", "content": prompt_text}]
        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            return result.get("sub_questions", [])
        except Exception:
            return [
                f"{techs} 功能覆盖度对比",
                f"{techs} 性能表现（吞吐量、延迟、资源消耗）",
                f"{techs} 社区活跃度与文档质量",
                f"{techs} 学习曲线与开发体验",
                f"{techs} 在 {state.scene} 场景下的适用性与部署复杂度",
            ]

    def _merge_and_build_response(self, state: SessionState, llm_result: dict) -> dict:
        if llm_result.get("scene") and not state.scene:
            state.scene = llm_result["scene"]
            if "scene" in state.missing_required:
                state.missing_required.remove("scene")
            if "scene" not in state.filled_required:
                state.filled_required.append("scene")

        if llm_result.get("complexity") and not state.complexity:
            state.complexity = llm_result["complexity"]
            if "complexity" in state.missing_required:
                state.missing_required.remove("complexity")
            if "complexity" not in state.filled_required:
                state.filled_required.append("complexity")

        if llm_result.get("candidate_techs") and not state.candidate_techs:
            state.candidate_techs = llm_result["candidate_techs"]
            if "candidate_techs" in state.missing_required:
                state.missing_required.remove("candidate_techs")
            if "candidate_techs" not in state.filled_required:
                state.filled_required.append("candidate_techs")

        if llm_result.get("unknown_techs") is not None:
            state.unknown_techs = llm_result["unknown_techs"]

        if llm_result.get("constraints"):
            for c in llm_result["constraints"]:
                if c not in state.constraints:
                    state.constraints.append(c)

        state.clarity_score = self._compute_score(state)
        return {
            "action": llm_result.get("action", "ask"),
            "answer": llm_result.get("message", ""),
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _fallback_response(self, state: SessionState) -> dict:
        return {
            "action": "ask",
            "answer": "抱歉，我刚才没理解清楚。能换个方式描述一下你的需求吗？",
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _apply_defaults(self, state: SessionState) -> None:
        if not state.scene:
            state.scene = "team"
            if "scene" in state.missing_required:
                state.missing_required.remove("scene")
            if "scene" not in state.filled_required:
                state.filled_required.append("scene")
        if not state.complexity:
            state.complexity = "medium"
            if "complexity" in state.missing_required:
                state.missing_required.remove("complexity")
            if "complexity" not in state.filled_required:
                state.filled_required.append("complexity")
        state.clarity_score = self._compute_score(state)

    def _compute_score(self, state: SessionState) -> float:
        total = 3
        filled = 0
        if state.candidate_techs:
            filled += 1
        if state.scene:
            filled += 1
        if state.complexity:
            filled += 1
        return round(filled / total, 2)
