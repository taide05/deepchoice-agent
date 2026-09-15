"""
DeepChoice — Tech Selection Deep Research Agent
Streamlit frontend with artistic dark-themed UI + multilingual support (zh/en/ja/ko)
"""
import html as _html
import json
import os
import time

import httpx
import streamlit as st

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
        "decision_title": "需要更多信息",
        "decision_reason": "暂停原因",
        "decision_gaps": "仍待补充的证据缺口",
        "decision_expires": "决定有效期至 {expires_at}",
        "decision_context_label": "补充背景信息（最多 4000 字符）",
        "decision_context_placeholder": "补充与技术选型有关的约束或使用场景...",
        "decision_provide_context": "补充信息并继续",
        "decision_limited_report": "基于现有证据生成受限报告",
        "decision_cancel": "取消任务",
        "decision_expired": "此决策已过期，任务已停止。请重新开始研究。",
        "decision_cancelled": "此任务已取消。",
        "decision_conflict": "决策状态已变化。页面已刷新；如提交结果不确定，可安全重试相同选择。",
        "decision_retry": "使用相同选择重试",
        "decision_network_error": "暂时无法确认提交结果。可以安全重试相同选择；补充内容不会显示在事件或日志中。",
        "decision_submit_error": "无法提交决策（HTTP {status}）。请刷新状态后重试。",
        "decision_invalid_context": "请先填写补充信息。",
        "decision_loading_error": "无法读取当前决策状态，请稍后重试。",
        "decision_pending": "研究已暂停，等待你的选择。",
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
        "obs_trace_fallback": "持久化运行追踪不可用（{reason}），以下显示现有快照观测数据。",
        "obs_trace_request_failed": "持久化运行追踪查询失败，以下显示现有快照观测数据。",
        "obs_durable_nodes": "持久化节点尝试",
        "obs_durable_calls": "持久化外部调用",
        "obs_durable_counts": "节点尝试 {attempts} · 节点重试 {retries} · 外部调用 {calls} · 失败调用 {failures}",
        "obs_status_label": "状态",
        "obs_call_node_label": "节点",
        "obs_call_attempt_label": "节点尝试",
        "obs_retry_no": "重试序号",
        "obs_attempt_label": "尝试",
        "obs_provider_label": "提供方",
        "obs_operation_label": "操作",
        "obs_duration_ms": "耗时（毫秒）",
        "obs_usage_partial": "Token 总量仅汇总已知用量，记录不完整。",
        "obs_usage_complete": "所有已记录 LLM 调用均包含 Token 用量。",
        "obs_no_durable_calls": "没有已记录的外部调用。",
        "budget_title": "运行预算",
        "budget_mode": "策略 {policy} · {mode}",
        "budget_usage": "用量 {used:,} / 上限 {limit:,}",
        "budget_settled": "已结算 {value:,}",
        "budget_reserved": "预留 {value:,}",
        "budget_unknown_spend": "未知用量 {value:,}（按预留上限计入）",
        "budget_soft_warning": "已达到软预算提醒阈值（80%）。",
        "budget_exhausted": "已触及预算上限。",
        "budget_admission_denied": "预算闸门拒绝了后续调用（资源：{resource}）；已消耗量仍按实际账本显示。",
        "budget_unknown_resource": "未知",
        "budget_unknown_cost": "成本金额未知，当前价格目录无法提供可靠估算。",
        "budget_unavailable": "预算信息不可用。",
        "budget_limited_report": "本报告受预算限制：{reason}",
        "budget_cap_reason": "已达到{resource}预算上限",
        "budget_total_tokens": "总 Token",
        "budget_llm_calls": "LLM 调用",
        "budget_retrieval_calls": "检索调用",
        "budget_active_milliseconds": "运行时间（毫秒）",
        "budget_resource_fallback": "预算资源 {resource}",
        "obs_unavailable": "不可用",
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
            "conclusion_synthesizer": "结论合成", "citation_validator": "引用验证", "report_generator": "报告生成", "self_reviewer": "自我审查",
        },
        "rv_toc_title": "目录",
        "rv_download_md": "下载 Markdown",
        "rv_download_pdf": "下载 PDF",
        "rv_pdf_unavailable": "PDF 不可用：请使用浏览器打印 (Ctrl+P)",
        "rv_download_failed": "下载失败",
        "rv_citations_empty": "本报告格式无引用标注",
        "rv_chain_anchor_note": "引用角标 [N] 对应下方证据链",
        "rv_citation_reason_supported": "确定性检查发现了支持证据。",
        "rv_citation_reason_missing": "未找到与该主张匹配的引用来源。",
        "rv_citation_reason_unavailable": "核验期间无法访问该来源。",
        "rv_citation_reason_inconclusive": "证据不足以判断；这不代表引用有误。",
        "rv_citation_reason_mismatch": "确定性检查未能确认来源支持该主张。",
        "rv_citation_reason_generic": "核验说明不可用，请人工复核。",
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
        "decision_title": "More information is needed",
        "decision_reason": "Why research paused",
        "decision_gaps": "Evidence gaps to address",
        "decision_expires": "Decision available until {expires_at}",
        "decision_context_label": "Additional context (up to 4,000 characters)",
        "decision_context_placeholder": "Add relevant constraints or usage context...",
        "decision_provide_context": "Provide context and continue",
        "decision_limited_report": "Generate a limited report from current evidence",
        "decision_cancel": "Cancel task",
        "decision_expired": "This decision expired and the task has stopped. Start a new research task.",
        "decision_cancelled": "This task was cancelled.",
        "decision_conflict": "The decision state changed. The page was refreshed; if the outcome is uncertain, retry the same choice safely.",
        "decision_retry": "Retry the same choice",
        "decision_network_error": "The submission outcome could not be confirmed. Retry the same choice safely; supplemental text is not shown in events or logs.",
        "decision_submit_error": "Could not submit the decision (HTTP {status}). Refresh the state and retry.",
        "decision_invalid_context": "Enter supplemental context first.",
        "decision_loading_error": "Could not load the current decision. Please retry shortly.",
        "decision_pending": "Research is paused and waiting for your choice.",
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
        "obs_trace_fallback": "Durable trace is unavailable ({reason}); showing snapshot observability panels.",
        "obs_trace_request_failed": "Durable trace query failed; showing snapshot observability panels.",
        "obs_durable_nodes": "Durable node attempts",
        "obs_durable_calls": "Durable external calls",
        "obs_durable_counts": "Node attempts {attempts} · Retries {retries} · External calls {calls} · Failed calls {failures}",
        "obs_status_label": "Status",
        "obs_call_node_label": "Node",
        "obs_call_attempt_label": "Node attempt",
        "obs_retry_no": "Retry number",
        "obs_attempt_label": "Attempt",
        "obs_provider_label": "Provider",
        "obs_operation_label": "Operation",
        "obs_duration_ms": "Duration (ms)",
        "obs_usage_partial": "Token totals sum known usage only; records are incomplete.",
        "obs_usage_complete": "Token usage is present for every recorded LLM call.",
        "obs_no_durable_calls": "No external calls were recorded.",
        "budget_title": "Run Budget",
        "budget_mode": "Policy {policy} · {mode}",
        "budget_usage": "Used {used:,} / limit {limit:,}",
        "budget_settled": "Settled {value:,}",
        "budget_reserved": "Reserved {value:,}",
        "budget_unknown_spend": "Unknown spend {value:,} (charged at reservation ceiling)",
        "budget_soft_warning": "The 80% soft budget warning threshold has been reached.",
        "budget_exhausted": "The budget limit has been reached.",
        "budget_admission_denied": "The budget gate denied a call (resource: {resource}); recorded consumption still reflects ledgered spend.",
        "budget_unknown_resource": "unknown",
        "budget_unknown_cost": "Cost is unknown; the current price catalog cannot provide a reliable estimate.",
        "budget_unavailable": "Budget information is unavailable.",
        "budget_limited_report": "This report is limited by the run budget: {reason}",
        "budget_cap_reason": "The {resource} budget limit was reached",
        "budget_total_tokens": "Total tokens",
        "budget_llm_calls": "LLM calls",
        "budget_retrieval_calls": "Retrieval calls",
        "budget_active_milliseconds": "Active time (ms)",
        "budget_resource_fallback": "Budget resource {resource}",
        "obs_unavailable": "Unavailable",
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
            "conclusion_synthesizer": "Conclusion Synthesis", "citation_validator": "Citation Verification", "report_generator": "Report Generation", "self_reviewer": "Self-Review",
        },
        "rv_toc_title": "Contents",
        "rv_download_md": "Download Markdown",
        "rv_download_pdf": "Download PDF",
        "rv_pdf_unavailable": "PDF unavailable — use browser print (Ctrl+P)",
        "rv_download_failed": "Download failed",
        "rv_citations_empty": "This report format has no citations",
        "rv_chain_anchor_note": "Citation badges [N] link to evidence chains below",
        "rv_citation_reason_supported": "Deterministic checks found supporting evidence.",
        "rv_citation_reason_missing": "No matching citation source was found for this claim.",
        "rv_citation_reason_unavailable": "The source could not be reached during verification.",
        "rv_citation_reason_inconclusive": "Evidence was inconclusive; this does not mean the citation is incorrect.",
        "rv_citation_reason_mismatch": "Deterministic checks did not establish support for this claim.",
        "rv_citation_reason_generic": "A safe verification explanation is unavailable; review manually.",
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
        "decision_title": "追加情報が必要です",
        "decision_reason": "一時停止の理由",
        "decision_gaps": "補足が必要な証拠の不足",
        "decision_expires": "決定期限: {expires_at}",
        "decision_context_label": "追加情報（最大 4000 文字）",
        "decision_context_placeholder": "技術選定に関する制約や利用状況を入力してください...",
        "decision_provide_context": "情報を補足して続行",
        "decision_limited_report": "現在の証拠で制限付きレポートを作成",
        "decision_cancel": "タスクをキャンセル",
        "decision_expired": "この決定は期限切れとなり、タスクは停止しました。新しく研究を開始してください。",
        "decision_cancelled": "このタスクはキャンセルされました。",
        "decision_conflict": "決定状態が変更されました。画面を更新しました。結果が不明な場合は同じ選択を安全に再試行できます。",
        "decision_retry": "同じ選択を再試行",
        "decision_network_error": "送信結果を確認できません。同じ選択を安全に再試行できます。補足情報はイベントやログに表示されません。",
        "decision_submit_error": "決定を送信できませんでした（HTTP {status}）。状態を更新して再試行してください。",
        "decision_invalid_context": "先に追加情報を入力してください。",
        "decision_loading_error": "現在の決定状態を読み込めません。しばらくしてから再試行してください。",
        "decision_pending": "研究は一時停止中です。選択してください。",
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
        "obs_trace_fallback": "永続トレースを利用できません（{reason}）。スナップショットの観測データを表示します。",
        "obs_trace_request_failed": "永続トレースの取得に失敗しました。スナップショットの観測データを表示します。",
        "obs_durable_nodes": "永続ノード試行",
        "obs_durable_calls": "永続外部呼び出し",
        "obs_durable_counts": "ノード試行 {attempts} · 再試行 {retries} · 外部呼び出し {calls} · 失敗 {failures}",
        "obs_status_label": "状態",
        "obs_call_node_label": "ノード",
        "obs_call_attempt_label": "ノード試行",
        "obs_retry_no": "再試行番号",
        "obs_attempt_label": "試行",
        "obs_provider_label": "プロバイダー",
        "obs_operation_label": "操作",
        "obs_duration_ms": "所要時間（ミリ秒）",
        "obs_usage_partial": "既知のトークン使用量のみを合算しています。記録は不完全です。",
        "obs_usage_complete": "記録されたすべての LLM 呼び出しにトークン使用量があります。",
        "obs_no_durable_calls": "外部呼び出しは記録されていません。",
        "budget_title": "実行予算",
        "budget_mode": "ポリシー {policy} · {mode}",
        "budget_usage": "使用量 {used:,} / 上限 {limit:,}",
        "budget_settled": "確定 {value:,}",
        "budget_reserved": "予約 {value:,}",
        "budget_unknown_spend": "不明な使用量 {value:,}（予約上限で計上）",
        "budget_soft_warning": "予算のソフト警告しきい値（80%）に達しました。",
        "budget_exhausted": "予算上限に達しました。",
        "budget_admission_denied": "予算ゲートが後続の呼び出しを拒否しました（リソース: {resource}）。消費量は記録済みの台帳に基づきます。",
        "budget_unknown_resource": "不明",
        "budget_unknown_cost": "費用は不明です。現在の価格カタログでは信頼できる推定を提供できません。",
        "budget_unavailable": "予算情報を利用できません。",
        "budget_limited_report": "このレポートは実行予算により制限されています: {reason}",
        "budget_cap_reason": "{resource}の予算上限に達しました",
        "budget_total_tokens": "合計トークン",
        "budget_llm_calls": "LLM 呼び出し",
        "budget_retrieval_calls": "検索呼び出し",
        "budget_active_milliseconds": "実行時間（ミリ秒）",
        "budget_resource_fallback": "予算リソース {resource}",
        "obs_unavailable": "利用不可",
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
            "conclusion_synthesizer": "結論合成", "citation_validator": "引用検証", "report_generator": "レポート生成", "self_reviewer": "自己レビュー",
        },
        "rv_toc_title": "目次",
        "rv_download_md": "Markdown をダウンロード",
        "rv_download_pdf": "PDF をダウンロード",
        "rv_pdf_unavailable": "PDF 利用不可：ブラウザで印刷してください (Ctrl+P)",
        "rv_download_failed": "ダウンロード失敗",
        "rv_citations_empty": "このレポート形式には引用がありません",
        "rv_chain_anchor_note": "引用バッジ [N] は以下の証拠チェーンに対応",
        "rv_citation_reason_supported": "決定的な検査で裏付ける証拠が見つかりました。",
        "rv_citation_reason_missing": "この主張に一致する引用元が見つかりませんでした。",
        "rv_citation_reason_unavailable": "検証中に情報源へアクセスできませんでした。",
        "rv_citation_reason_inconclusive": "証拠から判断できません。引用が誤りとは限りません。",
        "rv_citation_reason_mismatch": "決定的な検査では主張の裏付けを確認できませんでした。",
        "rv_citation_reason_generic": "安全な検証説明がありません。手動で確認してください。",
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
        "decision_title": "추가 정보가 필요합니다",
        "decision_reason": "일시 중지 이유",
        "decision_gaps": "보완이 필요한 증거 공백",
        "decision_expires": "결정 기한: {expires_at}",
        "decision_context_label": "추가 맥락 (최대 4,000자)",
        "decision_context_placeholder": "기술 선택과 관련된 제약이나 사용 맥락을 입력하세요...",
        "decision_provide_context": "정보를 보완하고 계속",
        "decision_limited_report": "현재 증거로 제한 보고서 생성",
        "decision_cancel": "작업 취소",
        "decision_expired": "결정이 만료되어 작업이 중지되었습니다. 새 연구를 시작하세요.",
        "decision_cancelled": "작업이 취소되었습니다.",
        "decision_conflict": "결정 상태가 변경되었습니다. 화면을 새로 고쳤습니다. 결과가 불확실하면 같은 선택을 안전하게 재시도할 수 있습니다.",
        "decision_retry": "같은 선택으로 재시도",
        "decision_network_error": "제출 결과를 확인할 수 없습니다. 같은 선택을 안전하게 재시도할 수 있습니다. 추가 내용은 이벤트나 로그에 표시되지 않습니다.",
        "decision_submit_error": "결정을 제출할 수 없습니다 (HTTP {status}). 상태를 새로 고친 뒤 재시도하세요.",
        "decision_invalid_context": "먼저 추가 맥락을 입력하세요.",
        "decision_loading_error": "현재 결정 상태를 불러오지 못했습니다. 잠시 후 다시 시도하세요.",
        "decision_pending": "연구가 일시 중지되었습니다. 선택해 주세요.",
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
        "obs_trace_fallback": "영구 추적을 사용할 수 없습니다({reason}). 스냅샷 관측 데이터를 표시합니다.",
        "obs_trace_request_failed": "영구 추적 조회에 실패했습니다. 스냅샷 관측 데이터를 표시합니다.",
        "obs_durable_nodes": "영구 노드 시도",
        "obs_durable_calls": "영구 외부 호출",
        "obs_durable_counts": "노드 시도 {attempts} · 재시도 {retries} · 외부 호출 {calls} · 실패 호출 {failures}",
        "obs_status_label": "상태",
        "obs_call_node_label": "노드",
        "obs_call_attempt_label": "노드 시도",
        "obs_retry_no": "재시도 번호",
        "obs_attempt_label": "시도",
        "obs_provider_label": "제공자",
        "obs_operation_label": "작업",
        "obs_duration_ms": "소요 시간(ms)",
        "obs_usage_partial": "알려진 토큰 사용량만 합산했으며 기록은 불완전합니다.",
        "obs_usage_complete": "기록된 모든 LLM 호출에 토큰 사용량이 있습니다.",
        "obs_no_durable_calls": "기록된 외부 호출이 없습니다.",
        "budget_title": "실행 예산",
        "budget_mode": "정책 {policy} · {mode}",
        "budget_usage": "사용량 {used:,} / 한도 {limit:,}",
        "budget_settled": "정산 {value:,}",
        "budget_reserved": "예약 {value:,}",
        "budget_unknown_spend": "알 수 없는 사용량 {value:,} (예약 상한으로 계산)",
        "budget_soft_warning": "예산 소프트 경고 임계값(80%)에 도달했습니다.",
        "budget_exhausted": "예산 한도에 도달했습니다.",
        "budget_admission_denied": "예산 게이트가 후속 호출을 거부했습니다(리소스: {resource}). 기록된 사용량은 원장 기준입니다.",
        "budget_unknown_resource": "알 수 없음",
        "budget_unknown_cost": "비용을 알 수 없습니다. 현재 가격표로는 신뢰할 수 있는 추정치를 제공할 수 없습니다.",
        "budget_unavailable": "예산 정보를 사용할 수 없습니다.",
        "budget_limited_report": "실행 예산으로 보고서가 제한되었습니다: {reason}",
        "budget_cap_reason": "{resource} 예산 한도에 도달했습니다",
        "budget_total_tokens": "총 토큰",
        "budget_llm_calls": "LLM 호출",
        "budget_retrieval_calls": "검색 호출",
        "budget_active_milliseconds": "실행 시간(ms)",
        "budget_resource_fallback": "예산 리소스 {resource}",
        "obs_unavailable": "사용 불가",
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
            "conclusion_synthesizer": "결론 합성", "citation_validator": "인용 검증", "report_generator": "보고서 생성", "self_reviewer": "자체 검토",
        },
        "rv_toc_title": "목차",
        "rv_download_md": "Markdown 다운로드",
        "rv_download_pdf": "PDF 다운로드",
        "rv_pdf_unavailable": "PDF 사용 불가 — 브라우저 인쇄 사용 (Ctrl+P)",
        "rv_download_failed": "다운로드 실패",
        "rv_citations_empty": "이 보고서 형식에는 인용이 없습니다",
        "rv_chain_anchor_note": "인용 배지 [N]은 아래 증거 체인에 연결",
        "rv_citation_reason_supported": "결정적 검사에서 근거를 뒷받침하는 증거를 찾았습니다.",
        "rv_citation_reason_missing": "이 주장에 맞는 인용 출처를 찾지 못했습니다.",
        "rv_citation_reason_unavailable": "검증 중 출처에 접근할 수 없었습니다.",
        "rv_citation_reason_inconclusive": "증거만으로 판단할 수 없습니다. 인용이 틀렸다는 뜻은 아닙니다.",
        "rv_citation_reason_mismatch": "결정적 검사에서 주장을 뒷받침하는 근거를 확인하지 못했습니다.",
        "rv_citation_reason_generic": "안전한 검증 설명을 사용할 수 없습니다. 직접 확인해 주세요.",
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
    .badge-verified { background: rgba(34, 197, 94, 0.12); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.25); }
    .badge-unsupported { background: rgba(239, 68, 68, 0.12); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25); }
    .badge-unreachable { background: rgba(249, 115, 22, 0.12); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.25); }
    .badge-unknown { background: rgba(161, 161, 170, 0.12); color: #d4d4d8; border: 1px solid rgba(161, 161, 170, 0.25); }

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

    .report-container sup a.cite { font-size: 0.65rem; font-weight: 700; color: #a78bfa; text-decoration: none; padding: 1px 5px; border-radius: 8px; background: rgba(124, 58, 237, 0.14); border: 1px solid rgba(124, 58, 237, 0.3); margin: 0 2px; }
    .report-container sup a.cite:hover { background: rgba(124, 58, 237, 0.3); color: #e4e4e7; }
    .toc-nav { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 14px; padding: 16px 18px; }
    .toc-nav a { color: #a1a1aa; text-decoration: none; display: block; padding: 3px 0; font-size: 0.82rem; line-height: 1.45; border-left: 2px solid transparent; padding-left: 10px; }
    .toc-nav a:hover { color: #c4b5fd; border-left-color: #7c3aed; }
    .toc-nav a.lvl2 { padding-left: 22px; font-size: 0.78rem; }
    .toc-nav a.lvl3 { padding-left: 34px; font-size: 0.75rem; color: #71717a; }
    .evidence-anchor { scroll-margin-top: 20px; }

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
    "citation_validator": "report_generation",
    "report_generator": "report_generation",
    "self_reviewer": "self_review",
}

# ═══════════════════════════════════════════════════════════════════════════
# Observability helpers (Task 3: timeline waterfall + panels)
# ═══════════════════════════════════════════════════════════════════════════
def _esc(text) -> str:
    """Escape source-provided text before injecting into HTML."""
    return _html.escape(str(text or ""), quote=True)


def _safe_external_href(value) -> str | None:
    """Return an escaped HTTP(S) link without credentials or unsafe ports."""
    from urllib.parse import urlsplit

    raw = str(value or "")
    if not raw or len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"}:
            return None
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.port is not None and parsed.port not in {80, 443}:
            return None
    except ValueError:
        return None
    return _esc(raw)


_CITATION_REASON_TEXT = {
    "lexical_support": "rv_citation_reason_supported",
    "citation_missing": "rv_citation_reason_missing",
    "source_not_found": "rv_citation_reason_missing",
    "source_ambiguous": "rv_citation_reason_missing",
    "not_cited": "rv_citation_reason_missing",
    "url_invalid": "rv_citation_reason_unavailable",
    "not_publicly_accessible": "rv_citation_reason_unavailable",
    "network_uncertain": "rv_citation_reason_inconclusive",
    "http_uncertain": "rv_citation_reason_inconclusive",
    "source_limit": "rv_citation_reason_inconclusive",
    "content_insufficient": "rv_citation_reason_inconclusive",
    "cross_language": "rv_citation_reason_inconclusive",
    "numeric_mismatch": "rv_citation_reason_mismatch",
    "negation_conflict": "rv_citation_reason_mismatch",
    "lexical_mismatch": "rv_citation_reason_mismatch",
}


def _citation_verification_display(status, reason, lang_code: str) -> tuple[str, str, str]:
    """Map untrusted citation metadata to a closed status label, CSS class, and text."""
    allowed = {"verified", "unsupported", "unreachable", "unknown"}
    safe_status = status if isinstance(status, str) and status in allowed else "unknown"
    reason_key = _CITATION_REASON_TEXT.get(reason) if isinstance(reason, str) else None
    if reason_key is None:
        reason_key = {
            "verified": "rv_citation_reason_supported",
            "unsupported": "rv_citation_reason_mismatch",
            "unreachable": "rv_citation_reason_unavailable",
            "unknown": "rv_citation_reason_inconclusive",
        }[safe_status]
    return safe_status.upper(), f"badge-{safe_status}", t(reason_key, lang_code)


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
                f'<div class="tl-time">{sec:.2f}s</div>'
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
    "research_failed": False,
    "research_events": [],
    "research_last_event_id": None,
    "research_task_version": None,
    "research_task_status": None,
    "research_snapshot": None,
    "research_report": None,
    "research_terminal_status": None,
    "research_connection_lost": False,
    "research_waiting_for_input": False,
    "research_decision": None,
    "research_decision_error": None,
    "research_decision_submission": None,
    "research_decision_clear_context_key": None,
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
    _, col_lang = st.columns([9, 1])
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
                st.markdown(f'<span class="badge badge-success">{_esc(tech_map.get(item, item))}</span>', unsafe_allow_html=True)
        if missing:
            st.markdown(f"**{t('missing', lang)}**")
            for item in missing:
                st.markdown(f'<span class="badge badge-weak">{_esc(tech_map.get(item, item))}</span>', unsafe_allow_html=True)

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
    clear_context_key = st.session_state.get("research_decision_clear_context_key")
    if clear_context_key:
        st.session_state.pop(clear_context_key, None)
        st.session_state.research_decision_clear_context_key = None

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
        f'<p class="app-subtitle">{t("researching", lang)} <strong style="color:#a78bfa">{_esc(task.get("query", "Tech comparison"))}</strong></p>',
        unsafe_allow_html=True,
    )

    if not st.session_state.get("research_started"):
        _start_research(task, data.get("sub_questions", []))
        st.session_state["research_started"] = True

    if st.session_state.research_running:
        _render_research_progress()

    current_decision = st.session_state.get("research_decision") or {}
    if (
        st.session_state.get("research_waiting_for_input")
        or current_decision.get("status") == "expired"
    ):
        _render_decision_panel()

    if st.session_state.research_complete:
        _render_results()

    if st.session_state.research_connection_lost:
        st.warning(t("loss_connection", lang))
        if st.button("重新连接", key="reconnect_durable_task"):
            st.session_state.research_connection_lost = False
            st.session_state.research_running = True
            st.rerun()

    if st.session_state.research_failed:
        st.error(t("loss_connection", lang))
        if (
            st.session_state.get("research_task_id")
            and st.session_state.get("research_terminal_status")
            in {"failed", "timed_out", "interrupted"}
            and st.button("恢复运行", key="resume_durable_task")
        ):
            try:
                resp = httpx.post(
                    f"{API_BASE}/api/v1/tasks/{st.session_state.research_task_id}/resume",
                    headers={"If-Match": str(st.session_state.get("research_task_version", 0))},
                    timeout=10,
                )
                if resp.status_code in (200, 202):
                    body = resp.json()
                    durable_task = body.get("task", {})
                    st.session_state.research_task_version = durable_task.get(
                        "version", st.session_state.research_task_version
                    )
                    st.session_state.research_failed = False
                    st.session_state.research_running = True
                    st.session_state.research_terminal_status = None
                    st.session_state.research_connection_lost = False
                    st.rerun()
                else:
                    st.error(f"恢复失败：HTTP {resp.status_code}")
            except Exception as exc:
                st.error(f"恢复失败：{exc}")
        if st.button(t("restart_btn", lang)):
            for k in DEFAULTS:
                st.session_state[k] = DEFAULTS[k]
            st.rerun()

    if (
        st.session_state.get("research_terminal_status") == "cancelled"
        and current_decision.get("status") != "expired"
    ):
        st.info(t("decision_cancelled", lang))
        if st.button(t("restart_btn", lang), key="restart_cancelled_task"):
            for k in DEFAULTS:
                st.session_state[k] = DEFAULTS[k]
            st.rerun()


def _start_research(task: dict, sub_questions: list[str]):
    payload = dict(task)
    payload["sub_questions"] = sub_questions
    try:
        resp = httpx.post(f"{API_BASE}/api/v1/tasks", json=payload, timeout=10)
        if resp.status_code in (200, 201, 202):
            body = resp.json()
            durable_task = body["task"]
            st.session_state.research_task_id = durable_task["task_id"]
            st.session_state.research_task_version = durable_task.get("version", 0)
            st.session_state.research_last_event_id = None
            st.session_state.research_running = True
        else:
            st.error(f"Failed to start research: HTTP {resp.status_code}")
            st.session_state.research_failed = True
    except Exception as e:
        st.error(f"Failed to start research: {e}")
        st.session_state.research_failed = True


def _sse_frames(lines):
    """Yield SSE frames and support multiline data fields."""
    frame, data_lines = {}, []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        # Older compatibility streams emitted one data line per event without
        # the SSE-required blank separator. Accept that form while keeping the
        # normal framed parser below.
        if line.startswith("data:") and data_lines and not frame.get("id") and not frame.get("event"):
            frame["data"] = "\n".join(data_lines)
            yield frame
            frame, data_lines = {}, []
        if not line:
            if frame or data_lines:
                if data_lines:
                    frame["data"] = "\n".join(data_lines)
                yield frame
            frame, data_lines = {}, []
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            data_lines.append(value)
        elif field in ("id", "event", "retry"):
            frame[field] = value
    if frame or data_lines:
        if data_lines:
            frame["data"] = "\n".join(data_lines)
        yield frame


def _task_detail(task_id: str):
    try:
        resp = httpx.get(f"{API_BASE}/api/v1/tasks/{task_id}", timeout=10)
        return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}


def _decision_task_projection(detail: dict) -> dict:
    task = detail.get("task", {}) if isinstance(detail, dict) else {}
    return task if isinstance(task, dict) else {}


def _remember_task_projection(detail: dict) -> dict:
    task = _decision_task_projection(detail)
    if task.get("version") is not None:
        st.session_state.research_task_version = task["version"]
    if task.get("status") is not None:
        st.session_state.research_task_status = task["status"]
    return task


def _set_waiting_for_input(detail: dict | None = None) -> bool:
    """Load authoritative task and pending-decision projections after an SSE pause."""
    task_id = st.session_state.get("research_task_id")
    if not task_id:
        return False
    if detail is None:
        detail = _task_detail(task_id)
    task = _remember_task_projection(detail)
    if task.get("status") != "waiting_for_input":
        return False

    st.session_state.research_running = False
    st.session_state.research_failed = False
    st.session_state.research_complete = False
    st.session_state.research_terminal_status = None
    st.session_state.research_connection_lost = False
    st.session_state.research_waiting_for_input = True
    try:
        response = httpx.get(
            f"{API_BASE}/api/v1/tasks/{task_id}/decision", timeout=10
        )
        decision = response.json() if response.status_code == 200 else {}
        if (
            response.status_code == 200
            and isinstance(decision, dict)
            and decision.get("status") == "pending"
        ):
            st.session_state.research_decision = decision
            st.session_state.research_decision_error = None
            return True
    except Exception:
        pass
    st.session_state.research_decision = None
    st.session_state.research_decision_error = t("decision_loading_error", lang)
    return True


def _refresh_decision_authority(task_id: str) -> tuple[dict, dict]:
    """Refresh both CAS version and public decision state before submitting."""
    detail_response = httpx.get(
        f"{API_BASE}/api/v1/tasks/{task_id}", timeout=10
    )
    detail = detail_response.json() if detail_response.status_code == 200 else {}
    task = _remember_task_projection(detail)
    decision_response = httpx.get(
        f"{API_BASE}/api/v1/tasks/{task_id}/decision", timeout=10
    )
    decision = decision_response.json() if decision_response.status_code == 200 else {}
    return task, decision


def _clear_decision_submission() -> None:
    submission = st.session_state.get("research_decision_submission") or {}
    decision = st.session_state.get("research_decision") or {}
    decision_id = submission.get("decision_id") or decision.get("decision_id")
    if decision_id:
        st.session_state.research_decision_clear_context_key = (
            f"decision_context_{decision_id}"
        )
    st.session_state.research_decision_submission = None


def _apply_authoritative_task_projection(task: dict) -> bool:
    """Move the visible lifecycle controls to the server's current task status."""
    status = task.get("status")
    if status is None:
        return False
    st.session_state.research_task_status = status
    if status in {
        "completed", "complete", "completed_with_warnings", "failed",
        "cancelled", "canceled", "timed_out", "timeout", "interrupted",
    }:
        st.session_state.research_waiting_for_input = False
        return _set_terminal_status(status)
    if status in {"queued", "running"}:
        st.session_state.research_waiting_for_input = False
        st.session_state.research_running = True
        st.session_state.research_complete = False
        st.session_state.research_failed = False
        st.session_state.research_terminal_status = None
        st.session_state.research_connection_lost = False
        return True
    if status == "waiting_for_input":
        st.session_state.research_waiting_for_input = True
        st.session_state.research_running = False
        st.session_state.research_complete = False
        st.session_state.research_failed = False
        st.session_state.research_terminal_status = None
        st.session_state.research_connection_lost = False
    return False


def _apply_decision_conflict(task: dict, decision: dict) -> bool:
    """Discard sensitive submitted text and render the refreshed server state."""
    _clear_decision_submission()
    if isinstance(decision, dict) and decision:
        st.session_state.research_decision = decision
    status = decision.get("status") if isinstance(decision, dict) else None
    if status == "expired":
        st.session_state.research_decision_error = t("decision_expired", lang)
    elif status == "cancelled":
        st.session_state.research_decision_error = t("decision_cancelled", lang)
    else:
        st.session_state.research_decision_error = t("decision_conflict", lang)
    _apply_authoritative_task_projection(task)
    # Rerun so a still-pending decision reopens all three choices, or a newer
    # task status returns to the stream/results/terminal view immediately.
    return True


def _apply_decision_resolution(payload: dict) -> bool:
    task_container = payload.get("task", {}) if isinstance(payload, dict) else {}
    task = _decision_task_projection(task_container)
    _remember_task_projection(task_container)
    _clear_decision_submission()
    st.session_state.research_decision = payload.get("decision")
    st.session_state.research_decision_error = None
    return _apply_authoritative_task_projection(task)


def _submit_decision(action: str, supplemental_input: str | None = None) -> bool:
    """Resolve a decision using a freshly-read task version and retryable body."""
    task_id = st.session_state.get("research_task_id")
    decision = st.session_state.get("research_decision") or {}
    if not task_id or not decision.get("decision_id"):
        st.session_state.research_decision_error = t("decision_loading_error", lang)
        return False
    if action == "provide_context":
        supplemental_input = str(supplemental_input or "").strip()
        if not supplemental_input:
            st.session_state.research_decision_error = t("decision_invalid_context", lang)
            return False
        body = {"action": action, "supplemental_input": supplemental_input}
    else:
        body = {"action": action}

    # Keep the exact request in session state across network uncertainty. This
    # lets the backend's body-hash idempotency make a retry safe without logging
    # or putting supplemental text into public events.
    submission = st.session_state.get("research_decision_submission")
    if submission is None:
        submission = {"decision_id": decision["decision_id"], "body": body}
        st.session_state.research_decision_submission = submission
    else:
        body = submission["body"]
        decision_id = submission["decision_id"]
        if decision_id != decision.get("decision_id"):
            st.session_state.research_decision_error = t("decision_conflict", lang)
            return False

    try:
        task, current_decision = _refresh_decision_authority(task_id)
        if task.get("version") is None:
            st.session_state.research_decision_error = t(
                "decision_loading_error", lang
            )
            return False
        if current_decision.get("status") == "expired":
            return _apply_decision_conflict(task, current_decision)
        # The backend accepts an identical body as an idempotent replay even
        # after queueing, so keep retrying it with the freshest task version.
        if (
            current_decision.get("status") == "pending"
            and task.get("status") != "waiting_for_input"
        ):
            return _apply_decision_conflict(task, current_decision)
        response = httpx.post(
            f"{API_BASE}/api/v1/tasks/{task_id}/decisions/{submission['decision_id']}",
            json=body,
            headers={"If-Match": str(task.get("version", 0))},
            timeout=15,
        )
        if response.status_code in (200, 202):
            accepted = response.json()
            if _apply_decision_resolution(accepted):
                return True
            st.session_state.research_decision_error = t("decision_conflict", lang)
            return False
        if response.status_code in (409, 410):
            refreshed_task, refreshed_decision = _refresh_decision_authority(task_id)
            return _apply_decision_conflict(refreshed_task, refreshed_decision)
        st.session_state.research_decision_error = t(
            "decision_submit_error", lang, status=response.status_code
        )
        return False
    except Exception:
        st.session_state.research_decision_error = t("decision_network_error", lang)
        return False


def _render_decision_panel():
    decision = st.session_state.get("research_decision")
    error = st.session_state.get("research_decision_error")
    if decision and decision.get("status") == "expired":
        st.info(t("decision_expired", lang))
        if st.button(t("restart_btn", lang), key="restart_expired_decision"):
            for key in DEFAULTS:
                st.session_state[key] = DEFAULTS[key]
            st.rerun()
        return
    if decision and decision.get("status") == "cancelled":
        st.info(t("decision_cancelled", lang))
        return
    if st.session_state.get("research_task_status") != "waiting_for_input":
        st.info(error or t("decision_conflict", lang))
        if st.button(t("decision_retry", lang), key="decision_refresh_task_state"):
            if not _set_waiting_for_input():
                st.session_state.research_decision_error = t("decision_conflict", lang)
            st.rerun()
        return
    if not decision or decision.get("status") != "pending":
        st.info(error or t("decision_pending", lang))
        if st.button(t("decision_retry", lang), key="decision_refresh_state"):
            _set_waiting_for_input()
            st.rerun()
        return

    st.subheader(t("decision_title", lang))
    st.caption(t("decision_pending", lang))
    st.markdown(f"**{t('decision_reason', lang)}**")
    st.text(decision.get("reason", ""))
    st.markdown(f"**{t('decision_gaps', lang)}**")
    gaps = decision.get("gaps", [])
    if gaps:
        for gap in gaps:
            st.text(f"• {gap}")
    else:
        st.write("—")
    st.caption(t("decision_expires", lang, expires_at=decision.get("expires_at", "—")))

    submission = st.session_state.get("research_decision_submission")
    if submission:
        body = submission["body"]
        action = body.get("action")
        st.info(error or t("decision_network_error", lang))
        if st.button(t("decision_retry", lang), key="decision_retry_same_body"):
            if _submit_decision(action, body.get("supplemental_input")):
                st.rerun()
        return

    context = st.text_area(
        t("decision_context_label", lang),
        placeholder=t("decision_context_placeholder", lang),
        max_chars=4000,
        key=f"decision_context_{decision.get('decision_id', 'pending')}",
    )
    if error:
        st.warning(error)
    actions = set(decision.get("allowed_actions", []))
    context_col, report_col, cancel_col = st.columns(3)
    with context_col:
        if "provide_context" in actions and st.button(
            t("decision_provide_context", lang),
            key="decision_provide_context",
            type="primary",
            use_container_width=True,
        ):
            if _submit_decision("provide_context", context):
                st.rerun()
    with report_col:
        if "limited_report" in actions and st.button(
            t("decision_limited_report", lang),
            key="decision_limited_report",
            use_container_width=True,
        ):
            if _submit_decision("limited_report"):
                st.rerun()
    with cancel_col:
        if "cancel" in actions and st.button(
            t("decision_cancel", lang),
            key="decision_cancel",
            use_container_width=True,
        ):
            if _submit_decision("cancel"):
                st.rerun()


def _set_terminal_status(status: str):
    if status not in {"completed", "complete", "completed_with_warnings", "failed", "cancelled", "canceled", "timed_out", "timeout", "interrupted"}:
        return False
    normalized = "cancelled" if status == "canceled" else "timed_out" if status == "timeout" else status
    st.session_state.research_running = False
    st.session_state.research_complete = status in {"completed", "complete", "completed_with_warnings"}
    st.session_state.research_failed = status not in {"completed", "complete", "completed_with_warnings", "cancelled", "canceled"}
    st.session_state.research_terminal_status = normalized
    st.session_state.research_task_status = normalized
    st.session_state.research_connection_lost = False
    return True


def _render_research_progress():
    task_id = st.session_state.research_task_id
    # A reconnect can begin after the decision.required event was already
    # acknowledged by Last-Event-ID. Since waiting_for_input is nonterminal,
    # that SSE stream would otherwise stay open without replaying the pause.
    if st.session_state.get("research_last_event_id"):
        current_detail = _task_detail(task_id)
        current_task = _remember_task_projection(current_detail)
        if current_task.get("status") == "waiting_for_input":
            if not _set_waiting_for_input(current_detail):
                st.session_state.research_running = False
                st.session_state.research_connection_lost = True
            return

    progress_bar = st.progress(0, text=t("progress_init", lang))
    live = st.empty()
    cancel_col, _ = st.columns([1, 4])
    with cancel_col:
        if st.button("取消", key="cancel_durable_task"):
            try:
                resp = httpx.post(
                    f"{API_BASE}/api/v1/tasks/{task_id}/cancel",
                    headers={"If-Match": str(st.session_state.get("research_task_version", 0))},
                    timeout=10,
                )
                if resp.status_code in (200, 202):
                    body = resp.json()
                    durable_task = body.get("task", {})
                    st.session_state.research_task_version = durable_task.get(
                        "version", st.session_state.research_task_version
                    )
                    if not _set_terminal_status(durable_task.get("status", "")):
                        st.session_state.research_running = True
                    st.rerun()
                else:
                    st.error(f"取消失败：HTTP {resp.status_code}")
            except Exception as exc:
                st.error(f"取消失败：{exc}")
    max_idx = 0
    live_nodes, live_order = {}, []
    first_ts = last_ts = None

    def _complete():
        progress_bar.progress(1.0, text=t("progress_done", lang))
        st.session_state.research_running = False
        st.session_state.research_complete = True

    try:
        got_terminal = False
        got_decision_pause = False
        for _attempt in range(3):
            headers = {}
            if st.session_state.get("research_last_event_id"):
                headers["Last-Event-ID"] = str(st.session_state.research_last_event_id)
            with httpx.stream("GET", f"{API_BASE}/api/v1/tasks/{task_id}/events",
                              headers=headers, timeout=httpx.Timeout(None, connect=15.0)) as resp:
                for frame in _sse_frames(resp.iter_lines()):
                    if frame.get("id"):
                        st.session_state.research_last_event_id = frame["id"]
                    try:
                        event = json.loads(frame.get("data", "{}"))
                    except json.JSONDecodeError:
                        continue
                    if frame.get("event") == "resync_required" or event.get("type") == "resync_required":
                        detail = event.get("snapshot") or {}
                        durable_task = _decision_task_projection(detail)
                        if event.get("latest_event_id") is not None:
                            st.session_state.research_last_event_id = str(
                                event["latest_event_id"]
                            )
                        if durable_task.get("version") is not None:
                            st.session_state.research_task_version = durable_task["version"]
                        if durable_task.get("status") == "waiting_for_input":
                            got_decision_pause = True
                            break
                        if _set_terminal_status(durable_task.get("status", "")):
                            got_terminal = True
                        if got_terminal:
                            break
                        continue
                    status = event.get("status")
                    if (
                        frame.get("event") == "decision.required"
                        or event.get("type") == "decision.required"
                        or status == "waiting_for_input"
                    ):
                        # Stop consuming this response as soon as the durable
                        # pause is observed. The task + decision GETs below are
                        # authoritative and avoid acting on stale SSE payloads.
                        got_decision_pause = True
                        break
                    if status in {
                        "completed", "completed_with_warnings", "failed",
                        "cancelled", "timed_out", "interrupted",
                    }:
                        # Replay may contain an old terminal run event followed
                        # by auto-resume/retry events for the same task. The
                        # current task projection is authoritative and refreshes
                        # the CAS version used by Resume.
                        detail = _task_detail(task_id)
                        durable_task = detail.get("task", {}) if isinstance(detail, dict) else {}
                        if durable_task.get("version") is not None:
                            st.session_state.research_task_version = durable_task["version"]
                        if _set_terminal_status(durable_task.get("status", "")):
                            got_terminal = True
                            break
                        continue
                    node = event.get("node")
                    if node == "__done__":
                        _complete(); got_terminal = True; break
                    if node == "__error__":
                        st.error(f"{t('loss_connection', lang)} {event.get('detail') or ''}")
                        st.session_state.research_running = False
                        st.session_state.research_failed = True
                        return
                    phase = event.get("phase") or NODE_TO_PHASE.get(node, "")
                    if phase in PHASES:
                        idx = PHASES.index(phase)
                        max_idx = max(max_idx, idx)
                        name = PHASE_NAME_MAP.get(phase, {}).get(lang, phase)
                        progress_bar.progress(max_idx / len(PHASES), text=t("progress_phase", lang, idx=idx+1, name=name))
                    if node:
                        ts_val = float(event.get("ts") or time.time())
                        seg_start = last_ts if last_ts is not None else ts_val
                        if node not in live_nodes:
                            live_order.append(node)
                        live_nodes[node] = {"start": seg_start, "end": ts_val}
                        if first_ts is None: first_ts = seg_start
                        last_ts = ts_val
                        running = _next_node_in_order(node)
                        entries = []
                        for name in live_order:
                            seg = live_nodes[name]
                            entries.append({"label": _node_label(name, lang), "running": name == running,
                                            "seconds": max(seg["end"] - seg["start"], 0.0)})
                        if running and running not in live_order:
                            entries.append({"label": _node_label(running, lang), "running": True})
                        live.markdown(_timeline_html(entries, max(last_ts - first_ts, 0.001), lang), unsafe_allow_html=True)
            if got_terminal:
                break
            if got_decision_pause:
                break
            detail = _task_detail(task_id)
            durable_task = detail.get("task", {}) if isinstance(detail, dict) else {}
            if durable_task.get("version") is not None:
                st.session_state.research_task_version = durable_task["version"]
            if durable_task.get("status") == "waiting_for_input":
                got_decision_pause = True
                break
            if _set_terminal_status(durable_task.get("status", "")):
                got_terminal = True; break
            time.sleep(0.25 * (_attempt + 1))
        if got_decision_pause:
            if not _set_waiting_for_input():
                st.session_state.research_running = False
                st.session_state.research_connection_lost = True
            return
        if not got_terminal:
            st.session_state.research_running = False
            st.session_state.research_failed = False
            st.session_state.research_connection_lost = True
    except Exception as e:
        st.error(f"{t('loss_connection', lang)} {e}")
        st.session_state.research_running = False
        st.session_state.research_failed = False
        st.session_state.research_connection_lost = True

    # Keep Streamlit's rerun control flow outside the network exception
    # boundary. Newer Streamlit releases implement rerun with an internal
    # exception that must not be reported as a connection failure.
    if st.session_state.research_complete:
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Observability Tab — durable Trace plus snapshot-backed research details
# ═══════════════════════════════════════════════════════════════════════════
def _render_obs_panels(
    snapshot: dict,
    observability: dict | None = None,
    *,
    observability_error: bool = False,
):
    durable_available = (
        isinstance(observability, dict)
        and observability.get("availability") == "available"
    )
    if observability_error:
        st.caption(t("obs_trace_request_failed", lang))
    elif isinstance(observability, dict) and not durable_available:
        st.caption(
            t(
                "obs_trace_fallback",
                lang,
                reason=observability.get("unavailable_reason")
                or t("obs_unavailable", lang),
            )
            )

    if isinstance(observability, dict):
        _render_durable_budget(observability.get("budget"))

    st.markdown(f"### {t('obs_timeline_title', lang)}")
    if durable_available:
        _render_durable_nodes(observability)
    else:
        _render_timeline_panel(snapshot)
    st.markdown(f"### {t('obs_retrieval_title', lang)}")
    _render_retrieval_panel(snapshot)
    st.markdown(f"### {t('obs_conflict_title', lang)}")
    _render_conflict_panel(snapshot)
    if durable_available:
        _render_durable_calls(observability)
    st.markdown(f"### {t('obs_token_title', lang)}")
    if durable_available:
        _render_durable_tokens(observability)
    else:
        _render_token_panel(snapshot)


def _render_durable_nodes(observability: dict):
    nodes = observability.get("nodes") or []
    totals = observability.get("totals") or {}
    st.caption(
        t(
            "obs_durable_counts",
            lang,
            attempts=totals.get("node_attempts", 0),
            retries=totals.get("node_retries", 0),
            calls=totals.get("external_calls", 0),
            failures=totals.get("failed_calls", 0),
        )
    )
    if not nodes:
        _render_timeline_panel({})
        return

    rows = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        duration = node.get("duration_ms")
        rows.append(
            "<tr>"
            f"<td>{_esc(_node_label(str(node.get('node_name') or ''), lang))}</td>"
            f"<td>{_esc(node.get('attempt_no', '—'))}</td>"
            f"<td>{_esc(node.get('status', '—'))}</td>"
            f"<td>{_esc(f'{duration:,}' if isinstance(duration, int) else '—')}</td>"
            "</tr>"
        )
    st.markdown(
        '<div class="report-container" style="padding:16px;"><table>'
        f"<tr><th>{t('obs_durable_nodes', lang)}</th>"
        f"<th>{t('obs_attempt_label', lang)}</th>"
        f"<th>{t('obs_status_label', lang)}</th>"
        f"<th>{t('obs_duration_ms', lang)}</th></tr>"
        f"{''.join(rows)}</table></div>",
        unsafe_allow_html=True,
    )


def _render_durable_calls(observability: dict):
    calls = observability.get("calls") or []
    totals = observability.get("totals") or {}
    st.markdown(f"### {t('obs_durable_calls', lang)}")
    if not calls:
        st.caption(t("obs_no_durable_calls", lang))
        return
    rows = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        duration = call.get("duration_ms")
        usage = call.get("usage") or {}
        usage_text = ", ".join(
            f"{_esc(label)}: {_esc(usage[field])}"
            for field, label in (
                ("input_tokens", "in"),
                ("output_tokens", "out"),
                ("total_tokens", "total"),
            )
            if field in usage
        ) or "—"
        rows.append(
            "<tr>"
            f"<td>{_esc(call.get('kind', '—'))}</td>"
            f"<td>{_esc(_node_label(str(call.get('node_name') or ''), lang))}</td>"
            f"<td>{_esc(call.get('node_attempt_no', '—'))}</td>"
            f"<td>{_esc(call.get('retry_no', '—'))}</td>"
            f"<td>{_esc(call.get('provider', '—'))}</td>"
            f"<td>{_esc(call.get('operation', '—'))}</td>"
            f"<td>{_esc(call.get('call_no', '—'))}</td>"
            f"<td>{_esc(call.get('status', '—'))}</td>"
            f"<td>{_esc(f'{duration:,}' if isinstance(duration, int) else '—')}</td>"
            f"<td>{usage_text}</td>"
            "</tr>"
        )
    st.markdown(
        '<div class="report-container" style="padding:16px;"><table>'
        f"<tr><th>Kind</th><th>{t('obs_call_node_label', lang)}</th>"
        f"<th>{t('obs_call_attempt_label', lang)}</th><th>{t('obs_retry_no', lang)}</th>"
        f"<th>{t('obs_provider_label', lang)}</th>"
        f"<th>{t('obs_operation_label', lang)}</th><th>Call</th>"
        f"<th>{t('obs_status_label', lang)}</th>"
        f"<th>{t('obs_duration_ms', lang)}</th><th>Tokens</th></tr>"
        f"{''.join(rows)}</table></div>",
        unsafe_allow_html=True,
    )


def _render_durable_tokens(observability: dict):
    totals = observability.get("totals") or {}
    if not totals.get("llm_calls"):
        st.caption(t("obs_no_token_data", lang))
        return
    values = (
        (t("obs_token_prompt_label", lang), totals.get("input_tokens")),
        (t("obs_token_completion_label", lang), totals.get("output_tokens")),
        (t("obs_token_total_label", lang), totals.get("total_tokens")),
    )
    rendered = " · ".join(
        f"{_esc(label)}: {_esc(f'{value:,}' if isinstance(value, int) else '—')}"
        for label, value in values
    )
    st.markdown(
        f'<div class="glass-card" style="padding:16px;">{rendered}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        t(
            "obs_usage_complete"
            if totals.get("token_usage_complete")
            else "obs_usage_partial",
            lang,
        )
    )


def _budget_resource_label(resource: str) -> str:
    key = {
        "total_tokens": "budget_total_tokens",
        "llm_calls": "budget_llm_calls",
        "retrieval_calls": "budget_retrieval_calls",
        "active_milliseconds": "budget_active_milliseconds",
    }.get(resource)
    if key is not None:
        return t(key, lang)
    return t("budget_resource_fallback", lang, resource=str(resource)[:60])


def _budget_resource_rows(budget: dict | None) -> list[dict]:
    """Convert public budget DTO data into display-only rows."""

    if not isinstance(budget, dict) or budget.get("availability") != "available":
        return []
    resources = budget.get("resources")
    if not isinstance(resources, dict):
        return []
    rows = []
    for resource, values in resources.items():
        if not isinstance(values, dict):
            continue
        label = _budget_resource_label(str(resource))
        if values.get("availability") != "available":
            rows.append({"label": label, "unavailable": True})
            continue
        limit = values.get("hard_limit")
        settled = values.get("settled")
        unknown = values.get("unknown_spend")
        reserved = values.get("reserved")
        if any(type(value) is not int or value < 0 for value in (limit, settled, unknown, reserved)):
            continue
        rows.append(
            {
                "label": label,
                "used": settled + unknown + reserved,
                "limit": limit,
                "settled": settled,
                "unknown_spend": unknown,
                "reserved": reserved,
                "soft_limit_reached": values.get("soft_limit_reached") is True,
                "exhausted": values.get("exhausted") is True,
                "unavailable": False,
            }
        )
    return rows


def _render_durable_budget(budget: dict | None):
    if not isinstance(budget, dict):
        return
    st.markdown(f"### {t('budget_title', lang)}")
    if budget.get("availability") != "available":
        st.caption(t("budget_unavailable", lang))
        return
    policy = budget.get("policy_version")
    mode = budget.get("enforcement_mode")
    if isinstance(policy, str) and isinstance(mode, str):
        st.caption(t("budget_mode", lang, policy=policy, mode=mode))
    if budget.get("admission_denied") is True:
        denied_resource = budget.get("denied_resource")
        resource_label = (
            _budget_resource_label(denied_resource)
            if isinstance(denied_resource, str)
            else t("budget_unknown_resource", lang)
        )
        st.warning(
            t("budget_admission_denied", lang, resource=resource_label),
            icon="⚠️",
        )
    rows = _budget_resource_rows(budget)
    if not rows:
        st.caption(t("budget_unavailable", lang))
        return
    for row in rows:
        if row["unavailable"]:
            st.markdown(f"**{row['label']}**")
            st.caption(t("budget_unknown_cost", lang))
            continue
        st.markdown(
            f"**{row['label']}** · "
            + t("budget_usage", lang, used=row["used"], limit=row["limit"])
        )
        if row["unknown_spend"]:
            st.caption(
                t("budget_unknown_spend", lang, value=row["unknown_spend"])
            )
        details = []
        if row["settled"]:
            details.append(t("budget_settled", lang, value=row["settled"]))
        if row["reserved"]:
            details.append(t("budget_reserved", lang, value=row["reserved"]))
        if details:
            st.caption(" · ".join(details))
        if row["exhausted"]:
            st.error(t("budget_exhausted", lang))
        elif row["soft_limit_reached"]:
            st.warning(t("budget_soft_warning", lang))


def _render_budget_limited_notice(snapshot: dict):
    limited = snapshot.get("budget_limited") if isinstance(snapshot, dict) else None
    if limited is True:
        reason = t("budget_unavailable", lang)
    elif isinstance(limited, dict) and limited.get("limited") is not False:
        reason_code = limited.get("reason")
        resource = limited.get("exhausted_resource") or limited.get("resource")
        if reason_code == "RUN_BUDGET_EXCEEDED" and isinstance(resource, str):
            reason = t(
                "budget_cap_reason",
                lang,
                resource=_budget_resource_label(resource),
            )
        elif isinstance(reason_code, str) and reason_code.strip():
            reason = reason_code.strip()[:180]
        elif isinstance(resource, str):
            reason = _budget_resource_label(resource)
        else:
            reason = t("budget_unavailable", lang)
    else:
        return
    st.warning(t("budget_limited_report", lang, reason=reason), icon="⚠️")


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
    for node in NODE_TO_PHASE:
        if node not in timing:
            continue
        sec = float(timing.get(node) or 0)
        total += sec
        entries.append({"label": _node_label(node, lang), "seconds": sec, "running": False})

    st.markdown(_timeline_html(entries, total, lang), unsafe_allow_html=True)
    st.caption(f"{t('obs_total_elapsed', lang)}: {total:.2f}s")


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
            f'<span class="badge badge-weak">{_esc(t("obs_partial_failures", lang, n=len(failures), list=", ".join(failures)))}</span>'
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


def _render_download_buttons(task_id: str, report_format: str):
    try:
        resp = httpx.get(
            f"{API_BASE}/api/v1/tasks/{task_id}/export",
            params={"format": "md", "report_format": report_format}, timeout=30,
        )
        if resp.status_code == 200:
            st.download_button(
                t("rv_download_md", lang), data=resp.content,
                file_name=f"deepchoice-report-{task_id}.md",
                mime="text/markdown", key="dl_md",
            )
        else:
            st.caption(f"{t('rv_download_failed', lang)}")
    except Exception:
        st.caption(f"{t('rv_download_failed', lang)}")

    try:
        resp = httpx.get(
            f"{API_BASE}/api/v1/tasks/{task_id}/export",
            params={"format": "pdf", "report_format": report_format}, timeout=60,
        )
        if resp.status_code == 200:
            st.download_button(
                t("rv_download_pdf", lang), data=resp.content,
                file_name=f"deepchoice-report-{task_id}.pdf",
                mime="application/pdf", key="dl_pdf",
            )
        elif resp.status_code == 501:
            st.caption(t("rv_pdf_unavailable", lang))
        else:
            st.caption(f"{t('rv_download_failed', lang)}")
    except Exception:
        st.caption(f"{t('rv_download_failed', lang)}")


def _render_results():
    task_id = st.session_state.research_task_id
    observability = None
    observability_error = False

    try:
        snap_resp = httpx.get(f"{API_BASE}/api/v1/tasks/{task_id}/snapshot", timeout=10)
        snapshot = snap_resp.json() if snap_resp.status_code == 200 else {}
        if isinstance(snapshot, dict) and "snapshot" in snapshot:
            snapshot = snapshot["snapshot"]
        st.session_state.research_snapshot = snapshot
    except Exception:
        snapshot = st.session_state.get("research_snapshot") or {}

    try:
        trace_resp = httpx.get(
            f"{API_BASE}/api/v1/tasks/{task_id}/observability", timeout=10
        )
        if trace_resp.status_code == 200:
            trace_payload = trace_resp.json()
            observability = trace_payload if isinstance(trace_payload, dict) else None
        else:
            observability_error = True
    except Exception:
        observability_error = True

    try:
        report_resp = httpx.get(f"{API_BASE}/api/v1/tasks/{task_id}/report", timeout=10)
        if report_resp.status_code == 200:
            st.session_state.research_report = report_resp.json()
    except Exception:
        pass

    n_chains = len(snapshot.get("evidence_chains", []))
    n_conflicts = len(snapshot.get("conflicts", []))
    confidence = snapshot.get("confidence", "unknown")

    st.markdown(f"""
    <div class="stat-row">
        <div class="stat-card"><div class="stat-value">{n_chains}</div><div class="stat-label">{t("stats_chains", lang)}</div></div>
        <div class="stat-card"><div class="stat-value">{n_conflicts}</div><div class="stat-label">{t("stats_conflicts", lang)}</div></div>
        <div class="stat-card"><div class="stat-value">{_esc(str(confidence).upper())}</div><div class="stat-label">{t("stats_confidence", lang)}</div></div>
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
        _render_obs_panels(
            snapshot, observability, observability_error=observability_error
        )

    with tab1:
        _render_budget_limited_notice(snapshot)
        fmt = st.selectbox(
            t("format_label", lang),
            ["what_why_how", "evidence_first", "comparison_matrix"],
            format_func=lambda x: t(f"format_{'www' if x == 'what_why_how' else ('ef' if x == 'evidence_first' else 'cm')}", lang),
            key="report_fmt",
        )
        try:
            resp = httpx.get(f"{API_BASE}/api/v1/tasks/{task_id}/annotated", params={"format": fmt}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                citations = data.get("citations", [])

                toc_col, report_col = st.columns([1, 3.6])
                with toc_col:
                    toc = data.get("toc", [])
                    if toc:
                        st.markdown(f"**{t('rv_toc_title', lang)}**")
                        links = "".join(
                            f'<a class="lvl{entry["level"]}" href="#{entry["id"]}">{_esc(entry["text"])}</a>'
                            for entry in toc
                        )
                        st.markdown(f'<div class="toc-nav">{links}</div>', unsafe_allow_html=True)
                    _render_download_buttons(task_id, fmt)

                with report_col:
                    report_html = data.get("report_html")
                    if isinstance(report_html, str):
                        st.markdown(
                            f'<div class="report-container">{report_html}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        # Compatibility with one-version-old servers: render
                        # Markdown with raw HTML disabled.
                        st.markdown(data.get("report", ""))

                if citations:
                    st.markdown(f"### {t('evidence_chains_title', lang)}")
                    st.caption(t("rv_chain_anchor_note", lang))
                    chains = snapshot.get("evidence_chains", [])
                    for cit in citations:
                        citation_n = cit.get("n")
                        if type(citation_n) is not int or citation_n <= 0:
                            continue
                        chain_idx = cit.get("chain_idx")
                        chain = chains[chain_idx] if isinstance(chain_idx, int) and 0 <= chain_idx < len(chains) else {}
                        strength = str(chain.get("evidence_strength", "weak")).lower()
                        if strength not in {"strong", "moderate", "weak"}:
                            strength = "weak"
                        disputed = chain.get("disputed", False)
                        badge = "badge-disputed" if disputed else f"badge-{strength}"
                        chain_sources = chain.get("sources", [])
                        source_idx = cit.get("source_idx")
                        source = None
                        if (isinstance(chain_sources, list) and isinstance(source_idx, int)
                                and 0 <= source_idx < len(chain_sources)):
                            source = chain_sources[source_idx]
                        if source is None and isinstance(chain_sources, list):
                            citation_url = cit.get("url", "")
                            citation_canonical = cit.get("canonical_url")
                            source = next((candidate for candidate in chain_sources
                                           if candidate.get("url") == citation_url
                                           or (citation_canonical and candidate.get("canonical_url") == citation_canonical)), None)
                        if not isinstance(source, dict):
                            source = {
                                "url": cit.get("url", ""),
                                "title": cit.get("title", ""),
                                "score": "",
                            }
                        url = str(cit.get("url") or source.get("url", ""))
                        title = _esc(source.get("title") or cit.get("title", ""))
                        safe_href = _safe_external_href(url)
                        if safe_href is not None:
                            link = (f'<a href="{safe_href}" target="_blank" '
                                    f'rel="noopener noreferrer nofollow" '
                                    f'style="color:#a78bfa; text-decoration:none;">{title}</a>')
                        else:
                            link = title
                        source_line = (
                            f'<div style="font-size:0.78rem; color:#71717a;">'
                            f'[{citation_n}] {link} '
                            f'(score: {_esc(source.get("score", ""))})</div>'
                        )
                        status_label, status_class, reason_text = _citation_verification_display(
                            cit.get("verification_status", "unknown"),
                            cit.get("verification_reason", "not_checked"),
                            lang,
                        )
                        st.markdown(f"""
                        <div class="glass-card evidence-anchor" id="ev-{citation_n}" style="padding:16px; margin-bottom:10px;">
                            <strong style="color:#e4e4e7">{_esc(chain.get("conclusion", "Finding")[:150])}</strong><br>
                            <span class="badge {badge}">{strength.upper()}</span>
                            {'<span class="badge badge-disputed">DISPUTED</span>' if disputed else ''}
                            <span class="badge {status_class}">{status_label}</span>
                            {source_line}
                            <div style="font-size:0.78rem; color:#a1a1aa;">{_esc(reason_text)}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.caption(t("rv_citations_empty", lang))
        except Exception as e:
            st.error(str(e))

    with tab2:
        st.markdown(f"### {t('source_ratings_title', lang)}")
        for s in snapshot.get("source_scores", [])[:12]:
            score = s.get("total_score", 0)
            score_color = "#4ade80" if score >= 7 else ("#fbbf24" if score >= 5 else "#f87171")
            st.markdown(f"""
            <div class="glass-card" style="padding:14px; margin-bottom:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="color:#e4e4e7; font-size:0.9rem;">{_esc(str(s.get("title", "Source"))[:70])}</strong>
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
