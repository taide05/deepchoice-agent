# V 记录：DeepChoice S 终态（2026-08-27）

## V1：改动登记

| 字段 | 内容 |
|------|------|
| 触发源 | S 终审四块扫描（暂停点 1）→ 用户裁决（阻断 1 全修=事件队列广播 / 重要 6 全修 / 优化 10 全做 / 债务 5 全修 / 声明不修 3 沿用 / 块4 移交 step ④）→ 修复 5 commits → 终验四重 |
| 触发原因 | S 块1-4 扫描：server 双执行（阻断）、失败态不落盘、LLM 零重试、Docker 不可复现、依赖无上限、CHROMA 路径不一致、连接泄漏、权威 JSON 伪造 retry 对、cv.typ 旧口径（移交）等 |
| 改动文件清单 | src/deepchoice/server/app.py、snapshot_store.py、utils/llm.py、agents/orchestrator.py、conflict_detector.py、retrievers/{tavily_keypool,official,learned_docs}.py、benchmarks/{metrics,merge_checkpoints,run_baseline}.py、pyproject.toml、Dockerfile、Dockerfile.frontend、README.md（Docker 段+路径）、template-data/metrics-snapshot.md、tests/ 7 文件 |
| 改动性质 | 修复 21 / 新增测试 11 / 数据声明 3 / 文件系统归档 2（未跟踪文件移 archive/） |
| 预期影响的测试 | 全量回归 + 新增：research_routes 4 组（B1/I1/I6）、llm retry 3、official 并发 1、CHROMA 路径 1、learned_docs 并发+原子写 2 |
| 预期影响的指标 | 无指标影响型改动（benchmark 走 CLI 直调 run_research_task，不触 server 路径；retry 指标伪造对删除=数据诚实性修复，权威指标不变）；测试数 186+1skip→**197+1skip** |
| 关联 commit | 57a63bb（G1）、ca00cd7（G2）、020212b（G3）、28ce89f（G4）、9650972（G5） |

## V2：验证执行

### 终验四重（S 出口）

| 重 | 内容 | 结果 |
|:--:|------|:--:|
| 1 全量测试 | pytest 全量 | **197 passed + 1 skipped**（321s；S 修复前 186+1skip）✅ |
| 2 benchmark 复核 | 权威 JSON 加载 + summary 8 指标逐项比对 snapshot（top1 0.909/recall 0.662/grounding 0.851/conflict 0.564/P50 255.6/P95 312.2/success 1.0/gradeA 100.0/official 0.656） | 全一致 ✅（retry_effectiveness 200 条 0/0 为历史伪造对——脚本已修复不再生成，snapshot 已加 not_measured 声明） |
| 3 静态检查 | pyflakes src+benchmarks+tests+frontend；vulture --min-confidence 80 | 双零 ✅ |
| 4 HTTP 冒烟（首建） | uvicorn :8124 一次性进程——health **200** / 不存在 task stream **404** / status **404** / POST 空 body **422**（校验层拒绝，零 LLM 副作用） | 四项全过 ✅（DC 无鉴权，401 项不适用；此口径记为本项目首建基线） |

### 200-case 时序核实（块3 产出，本终审最重前置）

三段 checkpoint 经内容/git diff/mtime 三重交叉核实，全覆盖 08-06 后全部代码批次——**无需重跑评测**。

## V3：数据归档

- 权威 benchmark 不变：`benchmarks/runs/benchmark-merged200-20260822-055123.json`
- 旧中间快照归档：benchmark-20260821-121925/134443.json → runs/archive/（未跟踪文件）
- 快照：template-data/metrics-snapshot.md 已修订（context_dependent 精确表述 + retry not_measured 声明 + 150c 指标链节点）
- S 报告：docs/superpowers/template-chain/2026-08-27-dc-s.md
- 终验 HTTP 冒烟为一次性进程（uvicorn :8124 已停），无归档文件——记录入本 v-record

## V4：回写

- S 报告（docs/superpowers/template-chain/2026-08-27-dc-s.md）：裁决/修复/终验记录已回填 ✅
- metrics-snapshot：表述修正 + 声明 + 指标链 ✅
- 状态：**暂停点 2——终验四重全绿，等用户确认进 DC 产出刷新（step ④：R/A/B/B2 轻量+补强，事实源=块4 事实权威表）**
