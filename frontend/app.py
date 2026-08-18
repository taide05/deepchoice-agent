"""
DeepChoice — Tech Selection Deep Research Agent
Streamlit frontend with artistic dark-themed UI + multilingual support (zh/en/ja/ko)
"""
import time
import json
import os
import html as _html
import streamlit as st
import httpx

st.set_page_config(
    page_title="DeepChoice — Tech Selection Research",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══════════════════════════════════════════════════════════════════════════
# i18n — All UI strings in 4 languages
# ═══════════════════════════════════════════════════════════════════════════
T = {
    "zh": {
        "title": "DeepChoice",
        "subtitle": "AI 驱动的技术选型深度研究",
        "welcome_icon": "",
        "welcome_title": "你要对比哪些技术方案？",
        "welcome_desc": "描述你想比较的技术 — 框架、数据库、工具、或整栈方案。<br>DeepChoice 跨 6 个数据源搜索，对证据质量打分，仲裁矛盾观点，<br>交付一份有据可查的研究报告。",
        "examples": ["FastAPI vs Flask REST API", "PostgreSQL vs MongoDB 数据分析", "Kubernetes vs Docker Swarm", "React vs Vue 初创看板", "Redis vs Kafka 事件流"],
        "input_placeholder": "描述你想比较什么...",
        "chat_placeholder": "输入你的回答...",
        "skip": "跳过",
        "clarity": "清晰度",
        "clarity_tooltip": "你的需求被定义得有多清晰",
        "known": "已收集",
        "missing": "待探明",
        "rounds_left": "剩余 {n} 轮澄清",
        "waiting": "请描述你的需求...",
        "recommend_title": "推荐技术",
        "recommend_caption": "点击勾选你想比较的技术",
        "compare_btn": "对比所选",
        "confirm_title": "确认研究",
        "confirm_scene": "场景: {scene}  |  复杂度: {complexity}",
        "start_research_btn": "开始深度研究",
        "researching": "研究中:",
        "progress_init": "初始化...",
        "progress_phase": "阶段 {idx}/7: {name}",
        "progress_done": "研究完成",
        "loss_connection": "与研究服务器连接中断:",
        "no_data_error": "没有研究数据，请返回重新澄清需求。",
        "restart_btn": "重新开始",
        "stats_chains": "证据链",
        "stats_conflicts": "发现矛盾",
        "stats_confidence": "置信度",
        "stats_formats": "报告格式",
        "tab_report": "  报告  ",
        "tab_evidence": "  证据  ",
        "tab_raw": "  原始数据  ",
        "format_www": "是什么 / 为什么 / 怎么做",
        "format_ef": "结论先行摘要",
        "format_cm": "五维对比矩阵",
        "format_label": "格式",
        "evidence_chains_title": "证据链",
        "source_ratings_title": "来源评分",
        "sources_label": "{n} 个来源",
        "authority_label": "权威",
        "time_label": "时效",
        "evidence_label": "可验证",
        "footer": "DeepChoice — AI 驱动的技术选型研究",
        "footer_tag": "证据支撑。冲突透明。可追溯。",
        "new_research_btn": "开始新研究",
        "tab_observability": "  观测  ",
        "obs_timeline_title": "运行轨迹时间轴",
        "obs_total_elapsed": "总耗时",
        "obs_no_timing": "暂无运行时间数据",
        "obs_running": "运行中",
        "obs_retrieval_title": "检索明细",
        "obs_status_ok": "成功",
        "obs_status_error": "失败",
        "obs_results_count": "{n} 条结果",
        "obs_latency_label": "耗时",
        "obs_error_label": "错误",
        "obs_partial_failures": "{n} 个来源部分失败：{list}",
        "obs_no_results": "暂无检索数据",
        "obs_conflict_title": "冲突仲裁",
        "obs_claim_score": "得分 {score}",
        "obs_resolution_label": "仲裁结果",
        "obs_res_a_correct": "A 正确",
        "obs_res_b_correct": "B 正确",
        "obs_res_both_partial": "双方部分成立",
        "obs_res_insufficient": "证据不足",
        "obs_confidence_label": "置信度",
        "obs_reasoning_label": "推理",
        "obs_key_factor_label": "关键因素",
        "obs_no_conflicts": "未发现矛盾——各来源观点一致",
        "obs_token_title": "Token 统计",
        "obs_token_agent_label": "Agent",
        "obs_token_model_label": "模型",
        "obs_token_calls_label": "调用",
        "obs_token_prompt_label": "输入 Tokens",
        "obs_token_completion_label": "输出 Tokens",
        "obs_token_total_label": "总 Tokens",
        "obs_token_totals_row": "合计",
        "obs_no_token_data": "暂无 Token 数据",
        "obs_nodes": {
            "query_analyzer": "查询分析", "query_adapter": "查询适配", "multi_retriever": "多源检索",
            "source_evaluator": "来源评估", "conflict_detector": "矛盾检测", "evidence_chain": "证据链构建",
            "conclusion_synthesizer": "结论合成", "report_generator": "报告生成", "self_reviewer": "自我审查",
        },
        "tech_map": {"candidate_techs": "候选技术", "scene": "使用场景", "complexity": "复杂度"},
    },
    "en": {
        "title": "DeepChoice",
        "subtitle": "AI-powered deep research for technology decisions",
        "welcome_icon": "",
        "welcome_title": "What technology are you evaluating?",
        "welcome_desc": "Describe what you want to compare — frameworks, databases, tools, or an entire stack.<br>DeepChoice searches across 6 sources, scores evidence quality, arbitrates conflicts,<br>and delivers an evidence-backed report you can trust.",
        "examples": ["FastAPI vs Flask for REST API", "PostgreSQL vs MongoDB for analytics", "Kubernetes vs Docker Swarm", "React vs Vue for a startup dashboard", "Redis vs Kafka for event streaming"],
        "input_placeholder": "Describe what you want to compare...",
        "chat_placeholder": "Type your response...",
        "skip": "Skip",
        "clarity": "Clarity",
        "clarity_tooltip": "How well-defined your requirements are",
        "known": "Known",
        "missing": "Missing",
        "rounds_left": "{n} clarification rounds remaining",
        "waiting": "Waiting for your input...",
        "recommend_title": "Recommended technologies",
        "recommend_caption": "Select the ones you want to compare",
        "compare_btn": "Compare selected",
        "confirm_title": "Confirm your research",
        "confirm_scene": "Scene: {scene}  |  Complexity: {complexity}",
        "start_research_btn": "Start Deep Research",
        "researching": "Researching:",
        "progress_init": "Initializing...",
        "progress_phase": "Phase {idx}/7: {name}",
        "progress_done": "Research complete",
        "loss_connection": "Lost connection to research server:",
        "no_data_error": "No research data. Please go back and re-clarify.",
        "restart_btn": "Restart",
        "stats_chains": "Evidence Chains",
        "stats_conflicts": "Conflicts Found",
        "stats_confidence": "Confidence",
        "stats_formats": "Report Formats",
        "tab_report": "  Report  ",
        "tab_evidence": "  Evidence  ",
        "tab_raw": "  Raw Data  ",
        "format_www": "What / Why / How",
        "format_ef": "Evidence-First Brief",
        "format_cm": "Comparison Matrix",
        "format_label": "Format",
        "evidence_chains_title": "Evidence Chains",
        "source_ratings_title": "Source Ratings",
        "sources_label": "{n} source(s)",
        "authority_label": "Authority",
        "time_label": "Time",
        "evidence_label": "Evidence",
        "footer": "DeepChoice — AI-powered technology selection research",
        "footer_tag": "Evidence-backed. Conflict-aware. Transparent.",
        "new_research_btn": "Start New Research",
        "tab_observability": "  Observability  ",
        "obs_timeline_title": "Run Timeline",
        "obs_total_elapsed": "Total elapsed",
        "obs_no_timing": "No timing data available",
        "obs_running": "Running",
        "obs_retrieval_title": "Retrieval Details",
        "obs_status_ok": "Success",
        "obs_status_error": "Failed",
        "obs_results_count": "{n} result(s)",
        "obs_latency_label": "Latency",
        "obs_error_label": "Error",
        "obs_partial_failures": "{n} source(s) partially failed: {list}",
        "obs_no_results": "No retrieval data",
        "obs_conflict_title": "Conflict Arbitration",
        "obs_claim_score": "Score {score}",
        "obs_resolution_label": "Resolution",
        "obs_res_a_correct": "A correct",
        "obs_res_b_correct": "B correct",
        "obs_res_both_partial": "Both partially",
        "obs_res_insufficient": "Insufficient data",
        "obs_confidence_label": "Confidence",
        "obs_reasoning_label": "Reasoning",
        "obs_key_factor_label": "Key factor",
        "obs_no_conflicts": "No conflicts found — all sources agree",
        "obs_token_title": "Token Usage",
        "obs_token_agent_label": "Agent",
        "obs_token_model_label": "Model",
        "obs_token_calls_label": "Calls",
        "obs_token_prompt_label": "Prompt Tokens",
        "obs_token_completion_label": "Completion Tokens",
        "obs_token_total_label": "Total Tokens",
        "obs_token_totals_row": "Total",
        "obs_no_token_data": "No token usage data",
        "obs_nodes": {
            "query_analyzer": "Query Analysis", "query_adapter": "Query Adaptation", "multi_retriever": "Multi-Source Retrieval",
            "source_evaluator": "Source Evaluation", "conflict_detector": "Conflict Detection", "evidence_chain": "Evidence Chain",
            "conclusion_synthesizer": "Conclusion Synthesis", "report_generator": "Report Generation", "self_reviewer": "Self-Review",
        },
        "tech_map": {"candidate_techs": "Tech candidates", "scene": "Usage scene", "complexity": "Complexity"},
    },
    "ja": {
        "title": "DeepChoice",
        "subtitle": "AI深層リサーチによる技術選定",
        "welcome_icon": "",
        "welcome_title": "どの技術を比較しますか？",
        "welcome_desc": "比較したい技術を記述してください。フレームワーク、データベース、ツール、またはスタック全体。<br>DeepChoiceは6つの情報源から検索し、証拠の品質をスコア化、矛盾を調停し、<br>信頼できるレポートを提供します。",
        "examples": ["FastAPI vs Flask REST API", "PostgreSQL vs MongoDB 分析", "Kubernetes vs Docker Swarm", "React vs Vue スタートアップ", "Redis vs Kafka イベントストリーミング"],
        "input_placeholder": "比較したい内容を説明してください...",
        "chat_placeholder": "回答を入力...",
        "skip": "スキップ",
        "clarity": "明確さ",
        "clarity_tooltip": "要件がどのくらい明確に定義されているか",
        "known": "収集済",
        "missing": "未収集",
        "rounds_left": "残り {n} ラウンド",
        "waiting": "入力を待っています...",
        "recommend_title": "お勧め技術",
        "recommend_caption": "比較したいものを選択してください",
        "compare_btn": "選択したものを比較",
        "confirm_title": "研究確認",
        "confirm_scene": "シーン: {scene}  |  複雑さ: {complexity}",
        "start_research_btn": "深層リサーチを開始",
        "researching": "研究中:",
        "progress_init": "初期化中...",
        "progress_phase": "フェーズ {idx}/7: {name}",
        "progress_done": "研究完了",
        "loss_connection": "サーバー接続が失われました:",
        "no_data_error": "研究データがありません。戻って再確認してください。",
        "restart_btn": "再開始",
        "stats_chains": "証拠チェーン",
        "stats_conflicts": "検出された矛盾",
        "stats_confidence": "信頼度",
        "stats_formats": "レポート形式",
        "tab_report": "  レポート  ",
        "tab_evidence": "  証拠  ",
        "tab_raw": "  生データ  ",
        "format_www": "何 / なぜ / どうするか",
        "format_ef": "結論先行ブリーフ",
        "format_cm": "比較マトリックス",
        "format_label": "形式",
        "evidence_chains_title": "証拠チェーン",
        "source_ratings_title": "情報源評価",
        "sources_label": "{n}件のソース",
        "authority_label": "権威性",
        "time_label": "時間",
        "evidence_label": "検証",
        "footer": "DeepChoice — AI深層リサーチによる技術選定",
        "footer_tag": "証拠に基づく。矛盾を検知。透明性。",
        "new_research_btn": "新しい研究を開始",
        "tab_observability": "  観測  ",
        "obs_timeline_title": "実行タイムライン",
        "obs_total_elapsed": "合計時間",
        "obs_no_timing": "タイミングデータがありません",
        "obs_running": "実行中",
        "obs_retrieval_title": "検索詳細",
        "obs_status_ok": "成功",
        "obs_status_error": "失敗",
        "obs_results_count": "{n}件の結果",
        "obs_latency_label": "所要時間",
        "obs_error_label": "エラー",
        "obs_partial_failures": "{n}個の情報源で部分障害: {list}",
        "obs_no_results": "検索データがありません",
        "obs_conflict_title": "競合調停",
        "obs_claim_score": "スコア {score}",
        "obs_resolution_label": "調停結果",
        "obs_res_a_correct": "A が正しい",
        "obs_res_b_correct": "B が正しい",
        "obs_res_both_partial": "両方とも部分的",
        "obs_res_insufficient": "証拠不十分",
        "obs_confidence_label": "信頼度",
        "obs_reasoning_label": "推論",
        "obs_key_factor_label": "決め手",
        "obs_no_conflicts": "矛盾は検出されませんでした",
        "obs_token_title": "トークン統計",
        "obs_token_agent_label": "エージェント",
        "obs_token_model_label": "モデル",
        "obs_token_calls_label": "呼び出し",
        "obs_token_prompt_label": "入力トークン",
        "obs_token_completion_label": "出力トークン",
        "obs_token_total_label": "合計トークン",
        "obs_token_totals_row": "合計",
        "obs_no_token_data": "トークンデータがありません",
        "obs_nodes": {
            "query_analyzer": "クエリ分析", "query_adapter": "クエリ適応", "multi_retriever": "マルチソース検索",
            "source_evaluator": "情報源評価", "conflict_detector": "矛盾検出", "evidence_chain": "証拠チェーン",
            "conclusion_synthesizer": "結論合成", "report_generator": "レポート生成", "self_reviewer": "自己レビュー",
        },
        "tech_map": {"candidate_techs": "候補技術", "scene": "利用シーン", "complexity": "複雑さ"},
    },
    "ko": {
        "title": "DeepChoice",
        "subtitle": "AI 기반 기술 선택 심층 연구",
        "welcome_icon": "",
        "welcome_title": "어떤 기술을 비교하시겠습니까?",
        "welcome_desc": "비교하고자 하는 기술을 설명해 주세요. 프레임워크, 데이터베이스, 도구, 또는 전체 스택.<br>DeepChoice는 6개 정보 소스로부터 검색하여 증거 품질을 평가하고, 모순을 중재하며,<br>신뢰할 수 있는 보고서를 제공합니다.",
        "examples": ["FastAPI vs Flask REST API", "PostgreSQL vs MongoDB 분석", "Kubernetes vs Docker Swarm", "React vs Vue 스타트업", "Redis vs Kafka 이벤트 스트리밍"],
        "input_placeholder": "비교하고 싶은 내용을 설명해 주세요...",
        "chat_placeholder": "응답을 입력하세요...",
        "skip": "건너뛰기",
        "clarity": "명확성",
        "clarity_tooltip": "요구 사항이 얼마나 명확히 정의되었는지",
        "known": "수집됨",
        "missing": "부족함",
        "rounds_left": "{n}회 남은 확인 단계",
        "waiting": "입력을 기다리는 중...",
        "recommend_title": "추천 기술",
        "recommend_caption": "비교할 항목을 선택하세요",
        "compare_btn": "선택 비교",
        "confirm_title": "연구 확인",
        "confirm_scene": "장면: {scene}  |  복잡도: {complexity}",
        "start_research_btn": "심층 연구 시작",
        "researching": "연구 중:",
        "progress_init": "초기화 중...",
        "progress_phase": "단계 {idx}/7: {name}",
        "progress_done": "연구 완료",
        "loss_connection": "연구 서버 연결 손실:",
        "no_data_error": "연구 데이터가 없습니다. 돌아가서 다시 확인해 주세요.",
        "restart_btn": "다시 시작",
        "stats_chains": "증거 체인",
        "stats_conflicts": "발견된 충돌",
        "stats_confidence": "신뢰도",
        "stats_formats": "보고서 형식",
        "tab_report": "  보고서  ",
        "tab_evidence": "  증거  ",
        "tab_raw": "  원본 데이터  ",
        "format_www": "What / Why / How",
        "format_ef": "결론 우선 브리프",
        "format_cm": "비교 매트릭스",
        "format_label": "형식",
        "evidence_chains_title": "증거 체인",
        "source_ratings_title": "출처 평가",
        "sources_label": "{n}개 출처",
        "authority_label": "권위",
        "time_label": "시간",
        "evidence_label": "검증",
        "footer": "DeepChoice — AI 기반 기술 선택 연구",
        "footer_tag": "증거 기반. 충돌 인식. 투명성.",
        "new_research_btn": "새 연구 시작",
        "tab_observability": "  관측  ",
        "obs_timeline_title": "실행 타임라인",
        "obs_total_elapsed": "총 소요 시간",
        "obs_no_timing": "타이밍 데이터 없음",
        "obs_running": "실행 중",
        "obs_retrieval_title": "검색 상세",
        "obs_status_ok": "성공",
        "obs_status_error": "실패",
        "obs_results_count": "{n}개 결과",
        "obs_latency_label": "소요 시간",
        "obs_error_label": "오류",
        "obs_partial_failures": "{n}개 출처 부분 실패: {list}",
        "obs_no_results": "검색 데이터 없음",
        "obs_conflict_title": "충돌 중재",
        "obs_claim_score": "점수 {score}",
        "obs_resolution_label": "중재 결과",
        "obs_res_a_correct": "A 정답",
        "obs_res_b_correct": "B 정답",
        "obs_res_both_partial": "둘 다 일부 정답",
        "obs_res_insufficient": "증거 부족",
        "obs_confidence_label": "신뢰도",
        "obs_reasoning_label": "추론",
        "obs_key_factor_label": "핵심 요인",
        "obs_no_conflicts": "충돌이 발견되지 않았습니다 — 모든 출처가 일치합니다",
        "obs_token_title": "토큰 통계",
        "obs_token_agent_label": "에이전트",
        "obs_token_model_label": "모델",
        "obs_token_calls_label": "호출",
        "obs_token_prompt_label": "입력 토큰",
        "obs_token_completion_label": "출력 토큰",
        "obs_token_total_label": "총 토큰",
        "obs_token_totals_row": "합계",
        "obs_no_token_data": "토큰 데이터 없음",
        "obs_nodes": {
            "query_analyzer": "쿼리 분석", "query_adapter": "쿼리 어댑터", "multi_retriever": "다중 소스 검색",
            "source_evaluator": "출처 평가", "conflict_detector": "충돌 탐지", "evidence_chain": "증거 체인",
            "conclusion_synthesizer": "결론 합성", "report_generator": "보고서 생성", "self_reviewer": "자체 검토",
        },
        "tech_map": {"candidate_techs": "후보 기술", "scene": "사용 환경", "complexity": "복잡도"},
    },
}

PHASE_NAME_MAP = {
    "query_analysis": {"zh": "分析查询", "en": "Analyzing Query", "ja": "クエリ分析", "ko": "쿼리 분석"},
    "retrieval": {"zh": "搜索信息源", "en": "Searching Sources", "ja": "情報源検索", "ko": "출처 검색"},
    "source_evaluation": {"zh": "评估来源", "en": "Evaluating Sources", "ja": "情報源評価", "ko": "출처 평가"},
    "conflict_detection": {"zh": "检测矛盾", "en": "Detecting Conflicts", "ja": "矛盾検出", "ko": "충돌 탐지"},
    "evidence_chain": {"zh": "构建证据链", "en": "Building Evidence", "ja": "証拠構築", "ko": "증거 체인 구축"},
    "report_generation": {"zh": "生成报告", "en": "Generating Report", "ja": "レポート生成", "ko": "보고서 생성"},
    "self_review": {"zh": "自我审查", "en": "Self-Reviewing", "ja": "自己レビュー", "ko": "자체 검토"},
    "complete": {"zh": "完成", "en": "Complete", "ja": "完了", "ko": "완료"},
}

LANG_FLAGS = {"zh": " CN", "en": " EN", "ja": " JP", "ko": " KR"}


def t(key: str, lang: str = "en", **fmt) -> str:
    """Get translated string with optional formatting."""
    s = T.get(lang, T["en"]).get(key, T["en"].get(key, key))
    if fmt:
        s = s.format(**fmt)
    return s


# ═══════════════════════════════════════════════════════════════════════════
# Custom CSS
# ═══════════════════════════════════════════════════════════════════════════
st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    * { font-family: 'Inter', -apple-system, 'Noto Sans SC', 'Noto Sans JP', 'Noto Sans KR', sans-serif; }

    .stApp { background: radial-gradient(ellipse at 20% 50%, #1a1040 0%, #0d0d1a 40%, #0a0a14 70%, #080810 100%); }
    .main .block-container { padding-top: 1.5rem; max-width: 1400px; }

    .bg-orb { position: fixed; border-radius: 50%; filter: blur(120px); z-index: -1; pointer-events: none; }
    .bg-orb-1 { width: 600px; height: 600px; top: -200px; left: -100px; background: rgba(102, 126, 234, 0.08); animation: orbFloat 20s ease-in-out infinite; }
    .bg-orb-2 { width: 400px; height: 400px; bottom: -150px; right: -100px; background: rgba(240, 147, 251, 0.06); animation: orbFloat 25s ease-in-out infinite reverse; }
    .bg-orb-3 { width: 350px; height: 350px; top: 50%; left: 50%; background: rgba(118, 75, 162, 0.06); animation: orbFloat 18s ease-in-out infinite 5s; }
    @keyframes orbFloat { 0%, 100% { transform: translate(0, 0) scale(1); } 33% { transform: translate(40px, -30px) scale(1.05); } 66% { transform: translate(-20px, 20px) scale(0.95); } }

    /* ── Top bar with lang ── */
    .top-bar { display: flex; justify-content: flex-end; margin-bottom: 8px; }
    /* Compact language selector pill */
    [data-testid="stSelectbox"]:has(#lang_selector) > div > div {
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        min-width: 80px !important;
        font-size: 0.8rem !important;
    }
    [data-testid="stSelectbox"]:has(#lang_selector) [data-baseweb="select"] [role="listbox"] {
        background: #1a1a2e !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
    }

    .app-title { font-size: 2.8rem; font-weight: 800; letter-spacing: -1px; margin: 0; background: linear-gradient(135deg, #a78bfa 0%, #7c3aed 30%, #ec4899 60%, #f59e0b 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .app-subtitle { color: #71717a; font-size: 0.95rem; margin-top: 0.2rem; margin-bottom: 1.5rem; font-weight: 400; }

    .hero-card { background: linear-gradient(135deg, rgba(124, 58, 237, 0.06) 0%, rgba(236, 72, 153, 0.04) 100%); border: 1px solid rgba(124, 58, 237, 0.12); border-radius: 24px; padding: 48px; text-align: center; max-width: 760px; margin: 50px auto; }
    .hero-icon { font-size: 3.5rem; margin-bottom: 20px; }
    .hero-title { font-size: 1.6rem; font-weight: 700; color: #e4e4e7; margin-bottom: 8px; }
    .hero-desc { color: #71717a; font-size: 0.95rem; line-height: 1.6; margin-bottom: 28px; }
    .hero-examples { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
    .hero-chip { background: rgba(124, 58, 237, 0.1); border: 1px solid rgba(124, 58, 237, 0.2); padding: 8px 18px; border-radius: 100px; color: #c4b5fd; font-size: 0.85rem; cursor: pointer; transition: all 0.2s; }
    .hero-chip:hover { background: rgba(124, 58, 237, 0.2); border-color: rgba(124, 58, 237, 0.4); }

    .glass-card { background: rgba(255, 255, 255, 0.025); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 18px; padding: 24px; margin-bottom: 16px; transition: all 0.25s ease; }
    .glass-card:hover { border-color: rgba(255, 255, 255, 0.12); box-shadow: 0 12px 40px rgba(0,0,0,0.3); transform: translateY(-1px); }

    .badge { padding: 3px 12px; border-radius: 100px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; margin: 2px 4px 2px 0; }
    .badge-strong { background: rgba(34, 197, 94, 0.12); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.25); }
    .badge-moderate { background: rgba(251, 191, 36, 0.12); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.25); }
    .badge-weak { background: rgba(239, 68, 68, 0.12); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25); }
    .badge-disputed { background: rgba(249, 115, 22, 0.12); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.25); }
    .badge-info { background: rgba(124, 58, 237, 0.12); color: #a78bfa; border: 1px solid rgba(124, 58, 237, 0.25); }
    .badge-success { background: rgba(34, 197, 94, 0.12); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.25); }

    .clarity-panel { background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 18px; padding: 28px; }
    .clarity-meter { width: 80px; height: 80px; border-radius: 50%; margin: 0 auto 16px; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; font-weight: 700; }
    .clarity-meter.low { border: 3px solid rgba(239, 68, 68, 0.3); color: #f87171; }
    .clarity-meter.mid { border: 3px solid rgba(245, 158, 11, 0.3); color: #fbbf24; }
    .clarity-meter.high { border: 3px solid rgba(34, 197, 94, 0.3); color: #4ade80; }

    .stProgress > div > div { background: rgba(255,255,255,0.04); border-radius: 10px; height: 6px; }
    .stProgress > div > div > div { background: linear-gradient(90deg, #7c3aed, #a855f7, #ec4899); border-radius: 10px; }

    .stButton > button { background: linear-gradient(135deg, #7c3aed 0%, #a855f7 50%, #ec4899 100%) !important; border: none !important; border-radius: 12px !important; color: white !important; font-weight: 600 !important; padding: 10px 24px !important; font-size: 0.9rem !important; transition: all 0.25s !important; letter-spacing: 0.3px; }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 8px 30px rgba(124, 58, 237, 0.4); }
    .stButton > button:active { transform: translateY(0); }

    .stTextInput > div > div > input, .stTextArea > div > div > textarea { background: rgba(255, 255, 255, 0.03) !important; border: 1px solid rgba(255, 255, 255, 0.08) !important; border-radius: 14px !important; color: #e4e4e7 !important; padding: 14px 18px !important; font-size: 0.95rem !important; }
    .stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus { border-color: rgba(124, 58, 237, 0.4) !important; box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1) !important; }
    .stSelectbox > div > div { background: rgba(255, 255, 255, 0.03) !important; border-radius: 12px !important; border: 1px solid rgba(255,255,255,0.06) !important; }

    .stat-row { display: flex; gap: 16px; margin-bottom: 20px; }
    .stat-card { flex: 1; background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.05); border-radius: 14px; padding: 20px; text-align: center; }
    .stat-value { font-size: 1.6rem; font-weight: 700; color: #e4e4e7; }
    .stat-label { font-size: 0.75rem; color: #52525b; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }

    /* ── Observability: timeline waterfall bars ── */
    .tl-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
    .tl-label { width: 150px; flex-shrink: 0; font-size: 0.78rem; color: #a1a1aa; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tl-track { flex: 1; background: rgba(255,255,255,0.04); border-radius: 6px; height: 16px; overflow: hidden; }
    .tl-bar { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #7c3aed, #a855f7, #ec4899); min-width: 28px; }
    .tl-bar-running { animation: tlPulse 1.5s ease-in-out infinite; }
    @keyframes tlPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
    .tl-time { width: 74px; flex-shrink: 0; font-size: 0.72rem; color: #71717a; font-family: 'JetBrains Mono', monospace; text-align: right; }
    .tl-time-running { color: #a78bfa; font-weight: 600; font-family: 'Inter', sans-serif; }

    /* ── Observability: conflict arbitration cards ── */
    .cf-claims { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
    .cf-side { flex: 1; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 10px 12px; font-size: 0.85rem; color: #e4e4e7; }
    .cf-vs { color: #52525b; font-weight: 700; font-size: 0.8rem; flex-shrink: 0; }
    .cf-reason { margin-top: 10px; font-size: 0.82rem; color: #a1a1aa; line-height: 1.5; }
    .cf-key { margin-top: 6px; font-size: 0.78rem; color: #c4b5fd; }
    .cf-meta { font-size: 0.75rem; color: #71717a; margin-left: 8px; }

    .report-container { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 18px; padding: 36px; }
    .report-container h1 { font-size: 1.6rem; color: #e4e4e7; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .report-container h2 { font-size: 1.2rem; color: #a78bfa; margin-top: 28px; }
    .report-container h3 { font-size: 1rem; color: #c4b5fd; margin-top: 20px; }
    .report-container table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    .report-container th { background: rgba(124, 58, 237, 0.1); color: #c4b5fd; padding: 10px 14px; text-align: left; font-size: 0.85rem; border-bottom: 1px solid rgba(255,255,255,0.08); }
    .report-container td { padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #a1a1aa; font-size: 0.85rem; }
    .report-container a { color: #a78bfa; text-decoration: none; }
    .report-container a:hover { text-decoration: underline; }
    .report-container ul, .report-container ol { color: #a1a1aa; }
    .report-container code { font-family: 'JetBrains Mono', monospace; background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }
    .report-container blockquote { border-left: 3px solid rgba(124, 58, 237, 0.3); padding-left: 16px; color: #71717a; margin-left: 0; }

    .app-footer { text-align: center; padding: 32px 0 16px; color: #3f3f46; font-size: 0.75rem; }
    .app-footer span { font-size: 0.7rem; }
</style>

<div class="bg-orb bg-orb-1"></div>
<div class="bg-orb bg-orb-2"></div>
<div class="bg-orb bg-orb-3"></div>
""", unsafe_allow_html=True)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
PHASES = ["query_analysis", "retrieval", "source_evaluation", "conflict_detection",
          "evidence_chain", "report_generation", "self_review"]

# Fallback copy of NODE_TO_PHASE from src/deepchoice/server/app.py (server is the
# single source of truth — keep the two tables in sync). Used only when a stream
# event is missing its "phase" field.
NODE_TO_PHASE = {
    "query_analyzer": "query_analysis",
    "query_adapter": "query_analysis",
    "multi_retriever": "retrieval",
    "source_evaluator": "source_evaluation",
    "conflict_detector": "conflict_detection",
    "evidence_chain": "evidence_chain",
    "conclusion_synthesizer": "evidence_chain",
    "report_generator": "report_generation",
    "self_reviewer": "self_review",
}

# ═══════════════════════════════════════════════════════════════════════════
# Observability helpers (Task 3: timeline waterfall + panels)
# ═══════════════════════════════════════════════════════════════════════════
def _esc(text) -> str:
    """Escape source-provided text before injecting into HTML."""
    return _html.escape(str(text or ""), quote=True)


def _node_label(node: str, lang_code: str) -> str:
    """Display name for a workflow node in the current language."""
    return t("obs_nodes", lang_code).get(node, node)


def _fmt_latency(ms) -> str:
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return "—"
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    return f"{ms:.0f} ms"


def _next_node_in_order(node: str) -> str | None:
    """Workflow-order successor of a node (None after the last node)."""
    keys = list(NODE_TO_PHASE.keys())
    if node not in keys:
        return None
    i = keys.index(node)
    return keys[i + 1] if i + 1 < len(keys) else None


def _timeline_html(entries: list[dict], total_seconds: float, lang_code: str) -> str:
    """Render horizontal waterfall bars (shared by live + post-completion views).

    entries: list of {"label", "seconds"} (completed) or {"label", "running"}.
    """
    rows = []
    for e in entries:
        label = _esc(e.get("label", ""))
        if e.get("running"):
            width = max(float(e.get("width") or 6), 1.0)
            rows.append(
                f'<div class="tl-row">'
                f'<div class="tl-label">{label}</div>'
                f'<div class="tl-track"><div class="tl-bar tl-bar-running" style="width:{width:.1f}%"></div></div>'
                f'<div class="tl-time tl-time-running">{t("obs_running", lang_code)}</div>'
                f'</div>'
            )
        else:
            sec = max(float(e.get("seconds") or 0), 0.0)
            pct = (sec / total_seconds * 100) if total_seconds > 0 else 0
            pct = max(min(pct, 100.0), 2.0)
            rows.append(
                f'<div class="tl-row">'
                f'<div class="tl-label">{label}</div>'
                f'<div class="tl-track"><div class="tl-bar" style="width:{pct:.2f}%"></div></div>'
                f'<div class="tl-time">{sec:.1f}s</div>'
                f'</div>'
            )
    return "".join(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Session State
# ═══════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "phase": "clarify",
    "clarify_session_id": None,
    "clarify_messages": [],
    "clarified_data": None,
    "research_task_id": None,
    "research_started": False,
    "research_running": False,
    "research_complete": False,
    "research_events": [],
    "lang": "zh",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

lang = st.session_state.lang


# ═══════════════════════════════════════════════════════════════════════════
# Language Selector (top-right, single compact dropdown)
# ═══════════════════════════════════════════════════════════════════════════
# Labels for each language in each locale
LANG_LABELS = {
    "zh": {"zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文"},
    "en": {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"},
    "ja": {"zh": "中国語", "en": "英語", "ja": "日本語", "ko": "韓国語"},
    "ko": {"zh": "중국어", "en": "영어", "ja": "일본어", "ko": "한국어"},
}

def render_top_bar():
    """Header bar with single language selector."""
    col_empty, col_lang = st.columns([9, 1])
    with col_lang:
        labels = LANG_LABELS[lang]
        options = list(labels.values())
        codes = list(labels.keys())
        current_idx = codes.index(lang)

        selected_label = st.selectbox(
            "Lang",
            options,
            index=current_idx,
            label_visibility="collapsed",
            key="lang_selector",
        )
        selected_code = codes[options.index(selected_label)]
        if selected_code != st.session_state.lang:
            st.session_state.lang = selected_code
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Clarify Phase
# ═══════════════════════════════════════════════════════════════════════════
def render_clarify_phase():
    st.markdown(f'<h1 class="app-title">{t("title", lang)}</h1>', unsafe_allow_html=True)
    st.markdown(f'<p class="app-subtitle">{t("subtitle", lang)}</p>', unsafe_allow_html=True)

    has_history = len(st.session_state.clarify_messages) > 0

    if not has_history:
        _render_welcome()
        return

    chat_col, info_col = st.columns([3, 1])

    with chat_col:
        for msg in st.session_state.clarify_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar=""):
                    st.markdown(msg["content"])
                    if msg.get("action") == "recommend" and msg.get("payload", {}).get("candidates"):
                        _render_tech_picker(msg["payload"]["candidates"])
                    if msg.get("action") == "confirm" and msg.get("payload"):
                        _render_confirm_section(msg["payload"])
            else:
                with st.chat_message("user", avatar=""):
                    st.markdown(msg["content"])

        c1, c2 = st.columns([5, 1])
        with c1:
            user_input = st.chat_input(t("chat_placeholder", lang), key="clarify_chat")
        with c2:
            skip = st.button(t("skip", lang), key="clarify_skip_btn", use_container_width=True)

        if user_input:
            _handle_clarify_message(user_input)
            st.rerun()
        if skip and st.session_state.clarify_session_id:
            _handle_skip()
            st.rerun()

    with info_col:
        _render_clarity_panel()


def _render_welcome():
    st.markdown(f"""
    <div class="hero-card">
        <div class="hero-icon">&#x1f52c;</div>
        <div class="hero-title">{t("welcome_title", lang)}</div>
        <div class="hero-desc">{t("welcome_desc", lang)}</div>
        <div class="hero-examples">
            {''.join(f'<div class="hero-chip">{e}</div>' for e in t("examples", lang))}
        </div>
    </div>
    """, unsafe_allow_html=True)

    user_input = st.chat_input(t("input_placeholder", lang), key="hero_chat")
    if user_input:
        _handle_clarify_message(user_input)
        st.rerun()


def _render_clarity_panel():
    st.markdown('<div class="clarity-panel">', unsafe_allow_html=True)
    st.markdown(f"**{t('clarity', lang)}**", help=t("clarity_tooltip", lang))

    if st.session_state.clarify_messages:
        last = st.session_state.clarify_messages[-1]
        score = last.get("clarity_score", 0)
        pct = int(score * 100)
        level = "high" if pct >= 70 else ("mid" if pct >= 40 else "low")
        st.markdown(f'<div class="clarity-meter {level}">{pct}%</div>', unsafe_allow_html=True)

        filled = last.get("filled_required", [])
        missing = last.get("missing_required", [])
        tech_map = t("tech_map", lang)

        if filled:
            st.markdown(f"**{t('known', lang)}**")
            for item in filled:
                st.markdown(f'<span class="badge badge-success">{tech_map.get(item, item)}</span>', unsafe_allow_html=True)
        if missing:
            st.markdown(f"**{t('missing', lang)}**")
            for item in missing:
                st.markdown(f'<span class="badge badge-weak">{tech_map.get(item, item)}</span>', unsafe_allow_html=True)

        rounds_left = 3 - last.get("clarify_rounds", 0)
        st.caption(t("rounds_left", lang, n=rounds_left))
    else:
        st.caption(t("waiting", lang))

    st.markdown('</div>', unsafe_allow_html=True)


def _render_tech_picker(candidates: list[dict]):
    st.markdown(f"**{t('recommend_title', lang)}**")
    st.caption(t("recommend_caption", lang))

    selected = []
    cols = st.columns(min(len(candidates), 3))
    for i, tech in enumerate(candidates):
        with cols[i % 3]:
            key = f"sel_{tech['name']}"
            is_sel = st.checkbox(
                f"{tech['name']}  \n*{tech.get('stars', '')}*  \n{tech.get('desc', '')}",
                key=key,
            )
            if is_sel:
                selected.append(tech["name"])

    if selected:
        if st.button(f"{t('compare_btn', lang)}: {', '.join(selected)}", type="primary"):
            _handle_clarify_message(", ".join(selected))
            st.rerun()


def _render_confirm_section(payload: dict):
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**{t('confirm_title', lang)}**")
        summary = payload.get("summary", "")
        st.markdown(summary)
        if payload.get("candidate_techs"):
            st.markdown("Comparing: " + "**, **".join(payload["candidate_techs"]))
        if payload.get("scene"):
            st.caption(t("confirm_scene", lang, scene=payload["scene"], complexity=payload.get("complexity", "N/A")))
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(t("start_research_btn", lang), type="primary", use_container_width=True):
            _handle_finalize()
            st.rerun()


def _handle_clarify_message(text: str):
    sid = st.session_state.clarify_session_id
    if sid is None:
        resp = httpx.post(f"{API_BASE}/clarify/start", json={"query": text}, timeout=10)
    else:
        resp = httpx.post(f"{API_BASE}/clarify/{sid}/message", json={"message": text}, timeout=10)

    if resp.status_code == 200:
        data = resp.json()
        st.session_state.clarify_session_id = data["session_id"]
        st.session_state.clarify_messages.append({"role": "user", "content": text})
        msg = {"role": "assistant", "content": data["answer"]}
        for k in ("action", "payload", "clarity_score", "filled_required", "missing_required", "clarify_rounds"):
            if k in data:
                msg[k] = data[k]
        st.session_state.clarify_messages.append(msg)
        if data.get("next_action") == "finalize":
            st.session_state.clarified_data = data.get("payload", {})


def _handle_skip():
    sid = st.session_state.clarify_session_id
    if sid:
        resp = httpx.post(f"{API_BASE}/clarify/{sid}/finalize", timeout=10)
        if resp.status_code == 200:
            st.session_state.clarified_data = resp.json().get("payload", {})
            st.session_state.phase = "research"
            st.rerun()


def _handle_finalize():
    sid = st.session_state.clarify_session_id
    if sid:
        resp = httpx.post(f"{API_BASE}/clarify/{sid}/finalize", timeout=10)
        if resp.status_code == 200:
            st.session_state.clarified_data = resp.json().get("payload", {})
            st.session_state.phase = "research"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Research Phase
# ═══════════════════════════════════════════════════════════════════════════
def render_research_phase():
    data = st.session_state.clarified_data
    if not data:
        st.error(t("no_data_error", lang))
        if st.button(t("restart_btn", lang)):
            for k in DEFAULTS:
                st.session_state[k] = DEFAULTS[k]
            st.rerun()
        return

    task = data.get("clarified_task", {})
    st.markdown(f'<h1 class="app-title">{t("title", lang)}</h1>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="app-subtitle">{t("researching", lang)} <strong style="color:#a78bfa">{task.get("query", "Tech comparison")}</strong></p>',
        unsafe_allow_html=True,
    )

    if not st.session_state.get("research_started"):
        _start_research(task, data.get("sub_questions", []))
        st.session_state["research_started"] = True

    if st.session_state.research_running:
        _render_research_progress()

    if st.session_state.research_complete:
        _render_results()


def _start_research(task: dict, sub_questions: list[str]):
    task["sub_questions"] = sub_questions
    try:
        resp = httpx.post(f"{API_BASE}/research", json=task, timeout=10)
        if resp.status_code == 200:
            st.session_state.research_task_id = resp.json()["task_id"]
            st.session_state.research_running = True
    except Exception as e:
        st.error(f"Failed to start research: {e}")


def _render_research_progress():
    task_id = st.session_state.research_task_id
    progress_bar = st.progress(0, text=t("progress_init", lang))
    live = st.empty()
    max_idx = 0
    # Live waterfall state (local to this script run; the authoritative
    # post-completion version renders from snapshot["agent_timing"]).
    live_nodes: dict = {}      # node -> last completed segment {"start": ts, "end": ts}
    live_order: list = []      # first-appearance order
    live_running = None        # node inferred to be running right now
    first_ts = None
    last_ts = None

    def _complete():
        progress_bar.progress(1.0, text=t("progress_done", lang))
        st.session_state.research_running = False
        st.session_state.research_complete = True
        st.rerun()

    try:
        with httpx.stream("GET", f"{API_BASE}/research/{task_id}/stream", timeout=300) as resp:
            got_done = False
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                node = event.get("node")

                if node == "__done__":
                    got_done = True
                    _complete()
                elif node == "__error__":
                    st.error(f"{t('loss_connection', lang)} {event.get('detail') or ''}")
                    st.session_state.research_running = False
                    return
                else:
                    phase = event.get("phase") or NODE_TO_PHASE.get(node, "")
                    if phase in PHASES:
                        idx = PHASES.index(phase)
                        # Monotonic: self_reviewer retries revisit earlier nodes.
                        max_idx = max(max_idx, idx)
                        name = PHASE_NAME_MAP.get(phase, {}).get(lang, phase)
                        progress_bar.progress(max_idx / len(PHASES), text=t("progress_phase", lang, idx=idx+1, name=name))

                    # Live waterfall: the stream emits updates-mode events, so an
                    # event means node N just COMPLETED at ts. The next node in
                    # workflow order is the one currently running.
                    if node:
                        ts_val = float(event.get("ts") or 0)
                        if ts_val <= 0:
                            ts_val = time.time()
                        seg_start = last_ts if last_ts is not None else ts_val
                        if node not in live_nodes:
                            live_order.append(node)
                        live_nodes[node] = {"start": seg_start, "end": ts_val}
                        if first_ts is None:
                            first_ts = seg_start
                        last_ts = ts_val
                        live_running = _next_node_in_order(node)

                        total_elapsed = max(last_ts - first_ts, 0.001)
                        entries = []
                        for name in live_order:
                            if name == live_running:
                                entries.append({"label": _node_label(name, lang), "running": True})
                            else:
                                seg = live_nodes[name]
                                entries.append({
                                    "label": _node_label(name, lang),
                                    "seconds": max(seg["end"] - seg["start"], 0.0),
                                    "running": False,
                                })
                        live.container().markdown(
                            _timeline_html(entries, total_elapsed, lang),
                            unsafe_allow_html=True,
                        )

            # Stream ended (EOF) without __done__ — the server may have crashed
            # mid-run. Ask /status once before declaring the connection lost.
            if not got_done:
                try:
                    status = httpx.get(f"{API_BASE}/research/{task_id}/status", timeout=10).json()
                except Exception:
                    status = {}
                if status.get("status") == "complete":
                    _complete()
                else:
                    st.error(t("loss_connection", lang))
                    st.session_state.research_running = False
    except Exception as e:
        st.error(f"{t('loss_connection', lang)} {e}")
        st.session_state.research_running = False


# ═══════════════════════════════════════════════════════════════════════════
# Observability Tab — four panels rendered from the research snapshot
# ═══════════════════════════════════════════════════════════════════════════
def _render_obs_panels(snapshot: dict):
    st.markdown(f"### {t('obs_timeline_title', lang)}")
    _render_timeline_panel(snapshot)
    st.markdown(f"### {t('obs_retrieval_title', lang)}")
    _render_retrieval_panel(snapshot)
    st.markdown(f"### {t('obs_conflict_title', lang)}")
    _render_conflict_panel(snapshot)
    st.markdown(f"### {t('obs_token_title', lang)}")
    _render_token_panel(snapshot)


def _render_timeline_panel(snapshot: dict):
    timing = snapshot.get("agent_timing") or {}
    if not timing:
        st.markdown(
            f'<div class="glass-card" style="padding:16px; color:#71717a; font-size:0.85rem;">{t("obs_no_timing", lang)}</div>',
            unsafe_allow_html=True,
        )
        return

    total = 0.0
    entries = []
    for node in NODE_TO_PHASE.keys():
        if node not in timing:
            continue
        sec = float(timing.get(node) or 0)
        total += sec
        entries.append({"label": _node_label(node, lang), "seconds": sec, "running": False})

    st.markdown(_timeline_html(entries, total, lang), unsafe_allow_html=True)
    st.caption(f"{t('obs_total_elapsed', lang)}: {total:.1f}s")


def _render_retrieval_panel(snapshot: dict):
    results = snapshot.get("search_results") or []
    failures = [str(f) for f in (snapshot.get("partial_failures") or [])]

    if not results:
        st.markdown(
            f'<div class="glass-card" style="padding:16px; color:#71717a; font-size:0.85rem;">{t("obs_no_results", lang)}</div>',
            unsafe_allow_html=True,
        )
        return

    if failures:
        st.markdown(
            f'<div class="glass-card" style="padding:14px; margin-bottom:10px; border-color:rgba(239,68,68,0.25);">'
            f'<span class="badge badge-weak">{t("obs_partial_failures", lang, n=len(failures), list=", ".join(failures))}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    for item in results:
        if not isinstance(item, dict):
            continue
        source = _esc(item.get("source") or "?")
        ok = str(item.get("status") or "").lower() == "success"
        badge_cls = "badge-success" if ok else "badge-weak"
        status_txt = t("obs_status_ok" if ok else "obs_status_error", lang)
        count = len(item.get("results") or [])
        error = item.get("error")
        error_html = (
            f'<div style="margin-top:8px; font-size:0.78rem; color:#f87171; '
            f'font-family:JetBrains Mono,monospace; word-break:break-all;">'
            f'{t("obs_error_label", lang)}: {_esc(str(error)[:300])}</div>'
            if error else ""
        )
        st.markdown(
            f"""
            <div class="glass-card" style="padding:16px; margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:#e4e4e7">{source}</strong>
                    <span class="badge {badge_cls}">{status_txt}</span>
                </div>
                <div style="margin-top:6px; font-size:0.78rem; color:#71717a;">
                    {t("obs_results_count", lang, n=count)} · {t("obs_latency_label", lang)}: {_fmt_latency(item.get("latency_ms"))}
                </div>
                {error_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


_RESOLUTION_BADGE = {
    "A_correct": ("obs_res_a_correct", "badge-success"),
    "B_correct": ("obs_res_b_correct", "badge-success"),
    "both_partial": ("obs_res_both_partial", "badge-moderate"),
    "insufficient_data": ("obs_res_insufficient", "badge-info"),
}


def _render_conflict_panel(snapshot: dict):
    conflicts = snapshot.get("conflicts") or []
    if not conflicts:
        st.markdown(
            f'<div class="glass-card" style="padding:16px; color:#71717a; font-size:0.85rem;">{t("obs_no_conflicts", lang)}</div>',
            unsafe_allow_html=True,
        )
        return

    for c in conflicts:
        if not isinstance(c, dict):
            continue
        claim_a = _esc(c.get("claim_a") or "—")
        claim_b = _esc(c.get("claim_b") or "—")
        score_a = (c.get("source_a") or {}).get("score")
        score_b = (c.get("source_b") or {}).get("score")
        score_a_html = (
            f' <span class="badge badge-info">{t("obs_claim_score", lang, score=score_a)}</span>'
            if score_a is not None else ""
        )
        score_b_html = (
            f' <span class="badge badge-info">{t("obs_claim_score", lang, score=score_b)}</span>'
            if score_b is not None else ""
        )

        resolution = str(c.get("resolution") or "unknown")
        res_key, res_cls = _RESOLUTION_BADGE.get(resolution, (None, "badge-info"))
        res_txt = t(res_key, lang) if res_key else _esc(resolution)

        confidence = c.get("confidence")
        conf_html = (
            f'<span class="cf-meta">{t("obs_confidence_label", lang)}: {_esc(str(confidence))}</span>'
            if confidence else ""
        )
        reasoning = c.get("reasoning")
        reason_html = (
            f'<div class="cf-reason">{t("obs_reasoning_label", lang)}: {_esc(str(reasoning))}</div>'
            if reasoning else ""
        )
        key_factor = c.get("key_factor")
        key_html = (
            f'<div class="cf-key">{t("obs_key_factor_label", lang)}: {_esc(str(key_factor))}</div>'
            if key_factor else ""
        )

        st.markdown(
            f"""
            <div class="glass-card" style="padding:16px; margin-bottom:10px;">
                <div class="cf-claims">
                    <div class="cf-side">{claim_a}{score_a_html}</div>
                    <div class="cf-vs">VS</div>
                    <div class="cf-side">{claim_b}{score_b_html}</div>
                </div>
                <div>
                    <span style="font-size:0.75rem; color:#52525b;">{t("obs_resolution_label", lang)}</span>
                    <span class="badge {res_cls}">{res_txt}</span>
                    {conf_html}
                </div>
                {reason_html}
                {key_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_token_panel(snapshot: dict):
    rows = snapshot.get("token_usage")
    if not rows:
        st.markdown(
            f'<div class="glass-card" style="padding:16px; color:#71717a; font-size:0.85rem;">{t("obs_no_token_data", lang)}</div>',
            unsafe_allow_html=True,
        )
        return

    # Rows are per-node-invocation: self_reviewer may appear multiple times
    # (retry loops). Group by agent, sum calls + tokens, merge models.
    grouped: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            calls = int(r.get("calls") or 0)
            prompt = int(r.get("prompt_tokens") or 0)
            completion = int(r.get("completion_tokens") or 0)
            total = int(r.get("total_tokens") or 0)
        except (TypeError, ValueError):
            continue  # malformed row — skip entirely
        agent = r.get("agent") or "unknown"
        g = grouped.setdefault(agent, {"models": [], "calls": 0, "prompt": 0, "completion": 0, "total": 0})
        model = r.get("model") or ""
        if model and model not in g["models"]:
            g["models"].append(model)
        g["calls"] += calls
        g["prompt"] += prompt
        g["completion"] += completion
        g["total"] += total

    if not grouped:
        st.markdown(
            f'<div class="glass-card" style="padding:16px; color:#71717a; font-size:0.85rem;">{t("obs_no_token_data", lang)}</div>',
            unsafe_allow_html=True,
        )
        return

    body = []
    tot = {"calls": 0, "prompt": 0, "completion": 0, "total": 0}
    for agent, g in grouped.items():
        tot["calls"] += g["calls"]
        tot["prompt"] += g["prompt"]
        tot["completion"] += g["completion"]
        tot["total"] += g["total"]
        models = ", ".join(g["models"]) or "—"
        body.append(
            f'<tr>'
            f'<td>{_esc(_node_label(agent, lang))}</td>'
            f'<td>{_esc(models)}</td>'
            f'<td style="text-align:right">{g["calls"]:,}</td>'
            f'<td style="text-align:right">{g["prompt"]:,}</td>'
            f'<td style="text-align:right">{g["completion"]:,}</td>'
            f'<td style="text-align:right">{g["total"]:,}</td>'
            f'</tr>'
        )
    body.append(
        f'<tr style="border-top:1px solid rgba(255,255,255,0.12);">'
        f'<td><strong>{t("obs_token_totals_row", lang)}</strong></td><td></td>'
        f'<td style="text-align:right"><strong>{tot["calls"]:,}</strong></td>'
        f'<td style="text-align:right"><strong>{tot["prompt"]:,}</strong></td>'
        f'<td style="text-align:right"><strong>{tot["completion"]:,}</strong></td>'
        f'<td style="text-align:right"><strong>{tot["total"]:,}</strong></td>'
        f'</tr>'
    )

    st.markdown(
        f'''
        <div class="report-container" style="padding:16px;">
        <table>
            <tr>
                <th>{t("obs_token_agent_label", lang)}</th>
                <th>{t("obs_token_model_label", lang)}</th>
                <th style="text-align:right">{t("obs_token_calls_label", lang)}</th>
                <th style="text-align:right">{t("obs_token_prompt_label", lang)}</th>
                <th style="text-align:right">{t("obs_token_completion_label", lang)}</th>
                <th style="text-align:right">{t("obs_token_total_label", lang)}</th>
            </tr>
            {''.join(body)}
        </table>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def _render_results():
    task_id = st.session_state.research_task_id

    try:
        snap_resp = httpx.get(f"{API_BASE}/research/{task_id}/snapshot", timeout=10)
        snapshot = snap_resp.json() if snap_resp.status_code == 200 else {}
    except Exception:
        snapshot = {}

    n_chains = len(snapshot.get("evidence_chains", []))
    n_conflicts = len(snapshot.get("conflicts", []))
    confidence = snapshot.get("confidence", "unknown")

    st.markdown(f"""
    <div class="stat-row">
        <div class="stat-card"><div class="stat-value">{n_chains}</div><div class="stat-label">{t("stats_chains", lang)}</div></div>
        <div class="stat-card"><div class="stat-value">{n_conflicts}</div><div class="stat-label">{t("stats_conflicts", lang)}</div></div>
        <div class="stat-card"><div class="stat-value">{confidence.upper()}</div><div class="stat-label">{t("stats_confidence", lang)}</div></div>
        <div class="stat-card"><div class="stat-value">3</div><div class="stat-label">{t("stats_formats", lang)}</div></div>
    </div>
    """, unsafe_allow_html=True)

    tab_obs, tab1, tab2, tab3 = st.tabs([
        t("tab_observability", lang),
        t("tab_report", lang),
        t("tab_evidence", lang),
        t("tab_raw", lang),
    ])

    with tab_obs:
        _render_obs_panels(snapshot)

    with tab1:
        fmt = st.selectbox(
            t("format_label", lang),
            ["what_why_how", "evidence_first", "comparison_matrix"],
            format_func=lambda x: t(f"format_{'www' if x == 'what_why_how' else ('ef' if x == 'evidence_first' else 'cm')}", lang),
            key="report_fmt",
        )
        try:
            resp = httpx.get(f"{API_BASE}/research/{task_id}/report", params={"format": fmt}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                st.markdown(f'<div class="report-container">{data["report"]}</div>', unsafe_allow_html=True)
        except Exception as e:
            st.error(str(e))

    with tab2:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"### {t('evidence_chains_title', lang)}")
            for c in snapshot.get("evidence_chains", [])[:12]:
                strength = c.get("evidence_strength", "weak")
                disputed = c.get("disputed", False)
                badge = "badge-disputed" if disputed else f"badge-{strength}"
                st.markdown(f"""
                <div class="glass-card" style="padding:16px; margin-bottom:10px;">
                    <strong style="color:#e4e4e7">{c.get("conclusion", "Finding")[:100]}</strong><br>
                    <span class="badge {badge}">{strength.upper()}</span>
                    {f'<span class="badge badge-disputed">DISPUTED</span>' if disputed else ''}
                    <div style="margin-top:8px; font-size:0.8rem; color:#71717a;">{t("sources_label", lang, n=len(c.get("sources", [])))}</div>
                </div>
                """, unsafe_allow_html=True)

        with col_b:
            st.markdown(f"### {t('source_ratings_title', lang)}")
            for s in snapshot.get("source_scores", [])[:12]:
                score = s.get("total_score", 0)
                score_color = "#4ade80" if score >= 7 else ("#fbbf24" if score >= 5 else "#f87171")
                st.markdown(f"""
                <div class="glass-card" style="padding:14px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <strong style="color:#e4e4e7; font-size:0.9rem;">{s.get("title", "Source")[:70]}</strong>
                        <span style="color:{score_color}; font-weight:700; font-size:1rem;">{score}</span>
                    </div>
                    <div style="font-size:0.75rem; color:#52525b; margin-top:4px;">
                        {t("authority_label", lang)}: {s["scores"]["authority"]} | {t("time_label", lang)}: {s["scores"]["timeliness"]} | {t("evidence_label", lang)}: {s["scores"]["verifiability"]}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    with tab3:
        st.json(snapshot)

    st.markdown(f"""
    <div class="app-footer">
        {t("footer", lang)}<br><span>{t("footer_tag", lang)}</span>
    </div>
    """, unsafe_allow_html=True)

    if st.button(t("new_research_btn", lang)):
        for k in DEFAULTS:
            st.session_state[k] = DEFAULTS[k]
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Main Router
# ═══════════════════════════════════════════════════════════════════════════
render_top_bar()

if st.session_state.phase == "clarify":
    render_clarify_phase()
else:
    render_research_phase()
