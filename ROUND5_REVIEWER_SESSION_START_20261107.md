# 新会话开场指令（承担第 5 轮独立审查）

> 用途：在 DSH 同一工作区（`D:\deepchoice-precodex`）新开一个会话，由该会话担任**独立第三层审查**，
> 执行 `ROUND5_SPOT_CHECK_PROMPT_20261107.md` 的全套抽检。把下方代码块内容整段粘给新会话即可。

```text
你是 DeepChoice 项目本轮交付的独立第三层审查员（独立抽检，不代表项目方）。你的任务是只读审查
D:\deepchoice-precodex 中的最终版 200 例结果，判断是否满足"抽检验证"口径；你不参与修复、不修改项目文件。

【硬性约束】
1. 只读：不得编辑/删除/覆盖任何已有文件，不得 git add/commit，不得运行测试或付费批次；
   唯一允许写入的文件是审查结果：D:\deepchoice-precodex\ROUND5_REVIEW_RESULT_20261107.md
   （以及你的临时草稿可放在 .scratch\layer3_round5\ 下）。
2. 不联网；只依赖本工作区文件与本地命令（读文件、SHA-256、git log 等）。
3. 你是独立审查，不要假设"项目方说的一定对"：所有数字都要回到产物/JSON 里自己核对；
   发现文档与产物不一致时，按 blocker 记录（文件:行号），不要自行修改。
4. 不启动任何模型调用批次/研究请求；不消耗 API 额度。
5. 本轮是"候选最终版"抽检：抽检通过前，任何地方都不得写成"最终验收通过"；你的结论也只能是
   "抽检验证通过/不通过"，且必须声明：AI 辅助抽检 ≠ 真人签字，样本不可外推全量 200。

【第一步：读任务书】
先完整读 D:\deepchoice-precodex\ROUND5_SPOT_CHECK_PROMPT_20261107.md，
它是你的任务规格（背景、三部分任务、输出格式、判定口径 v1.2.7）。严格按它执行。

【第二步：独立核对的关键事实（自己从文件核验，不要照抄）】
- 最终批次：D:\deepchoice-precodex\.scratch\cases\runs\final-200-finalcode-20261106
  （summary.json / batch_meta.json / batch_health.json / review_final_200.json / FIX39_PROVENANCE.json / FIX4LAST_PROVENANCE.json）
- 修复批：...\runs\final-200-fix39-20261106、...\runs\final-200-fix4last-20261107、
  ...\runs\final-200-invalid-rerun138-20261106
- 冻结：FREEZE_20261107.md、FREEZE_MANIFEST_20261107.json（代码提交应为 da99f23，src_tree SHA 以 manifest 为准；
  可用 python 重新计算 src/**/*.py 的聚合 SHA 对比）
- 最终报告：FINAL200_FINAL_RESULT_20261107.md（宣称 C4=1/200=174、C2=true 182、usable 199、DG 182、
  花费 42,422,985 超上限 22,985）
- 评审口径：INDEPENDENT_REVIEW_CARD_20261104.md 附录一/二/三 + 第 5 轮口令第五节（v1.2.7）
- 历史/披露：CALIBRATION_RESULT_20261106.md、AI_SPOT_CHECK_LAYER3_20261104.md、SESSION_CHECKPOINT_20261107.md

【第三步：按任务书三部分执行】
A. 修复验证：按口令第一部分做 SHA 核对（4 例 fix4last + 抽 6 例 fix39 + F200-138），
   再按 v1.2.7 复评这 10 例（全报告阅读，重点：分支互斥/优先级/翻转门控、未声明前提、检索缺口、
   属性归属、未调和矛盾）。预期除 F200-174（已披露 C4=1）外均为 C4=0；有异常给行号证据。
B. 新抽样：按口令第二部分，从 126 例池（排除 74 个 ID 后）用种子 2026110701 抽 8–10 例，
   按 v1.2.7 同口径评（C1–C4、D1–D5、C2 五判据+可比性、notes≤80 字带行号）。
C. 文档/一致性核验：按口令第三部分逐项"通过/不通过 + 依据"（指标一致性、冻结 SHA/commit、
   provenance 与无替换、预算超支披露、状态措辞、旧批指标未混用、样本未外推）。
   另外检查：F200-174 的披露是否准确（报告中是否明确列出且未掩盖）。

【第四步：交付】
1. 写 ROUND5_REVIEW_RESULT_20261107.md，包含：
   - 逐例 JSON（修复验证 10 例 + 新抽 8–10 例，字段按口令格式）
   - 汇总：SHA 核对结果、C4/usable/DG 与两层记录一致率（写清分母）、预期差异（如 174）
   - 文档核验逐项结果（通过/不通过 + 行号）
   - 结论字段：repair_verified、c2_records_ok、doc_sync_ok、sample_pass、can_mark_final、blockers
   - 声明：AI 辅助抽检、非真人签字、样本不可外推、全量残余风险已披露
2. 在聊天里给一份 ≤300 字摘要（结论字段 + 关键 blocker + 结果文件路径）。
3. 若发现口令要求与文件实际不符（路径不存在、数值对不上），不要猜测，记录 blocker 并继续其余部分。
```

## 给用户的用法

1. 在 DSH 中新建会话，工作区选 `D:\deepchoice-precodex`；
2. 把上面代码块整段粘进去；
3. 等它输出 `ROUND5_REVIEW_RESULT_20261107.md` 与摘要，把摘要贴回当前会话即可。
