# 评估工具入口

更新：2026-10-01。本页仅说明已实现工具。目标见[质量路线](../docs/current-roadmap.md)，
判据见[quality-selection-v1](../docs/product-effectiveness-optimization.md)，实际预算与结果见
[当前状态](../docs/o1-execution-status.md)。四例开发清单已冻结，四例新保留集独立封存。
新串行运行适配已执行首批开发对照，但发现准备过程遗漏运行时种子审定文件，且候选触发预算停止。
实际结果与账本见当前状态。修复后的准备接口强制保留四项运行输入，并为已记录的事故提供一次性维修基线入口。

## quality-selection-v1 操作接口

所有命令从干净的采集器 checkout 运行。Python 3.11/3.12 的 `PYTHONPATH` 指向绑定的
生产 checkout 的 `src`；基线可以使用改动前生产提交，采集器提交单独记录。`--env-file`
只读加载本地配置，不复制或输出密钥。以下为接口示意，路径均指忽略区内人工审阅后的材料：

```powershell
python -m benchmarks.quality_selection_runtime init-ledger --reconciliation <reconciliation.json>
python -m benchmarks.quality_selection_runtime freeze --spec <spec.json> --binding <fresh-root/binding.json> --env-file <private-env>
python -m benchmarks.quality_selection_runtime serve --binding <fresh-root/binding.json> --env-file <private-env> --port 8765
python -m benchmarks.quality_selection validate --binding <fresh-root/binding.json>
python -m benchmarks.quality_selection collect --binding <fresh-root/binding.json> --output <fresh-collection-root> --api-base http://127.0.0.1:8765 --execute-paid-runs
```

- `init-ledger` 是首次对账后的显式操作。对账 JSON 包含 `protocol`、`used:114`、
  `new_protocol_admissions:0`、`reviewed:true` 与已核对证据的 `evidence_path`/`evidence_sha256`，摘要须与实际文件相等。
  必须先核实历史累计及新协议尚无准入；不能编造凭据以重置额度。固定账本位于采集器
  checkout 的 `outputs/quality-selection-v1-ledger.sqlite3`，另有身份及逐笔准入见证文件；
  一起保存。冻结/采集不会自动建库，缺文件、身份不符或两份准入记录不一致均须先对账。
- spec 包含 `phase`（`baseline/candidate/followup/repair_baseline/reviewed_candidate/delivery_candidate/acceptance`）、`production_root`、
  `seed_path`/`seed_sha256`、`preflight_path`、`datasets`、`source_policy` 和开发例 `hitl`。
  dataset 项为 `split/path/sha256`，只能引用已冻结版本。来源政策必须声明
  `holdout_reference_ingestion:false`，并用 `development_exposure` 说明开发材料与知识种子的关系。
  每例 HITL 固定 `action`、可选 `repeat_action`、需要时的 `supplemental_input`；保留例采用封存规则。
- candidate/followup 另需 `baseline_binding_path`：原请求、HITL、模型、配置、依赖、种子、
  嵌入版本、采集器提交及来源政策必须一致，比较窗口不超过7天。acceptance 另需
  `candidate_lock_path`，指向已完成开发评审的 `accepted:true`/`candidate_commit` 记录；
  该记录另含 `candidate_binding` 的 `path/sha256`。校验开发候选绑定及运行条件后才能读保留材料，
  开发HITL沿用锁定规则且同例三次相同。锁定记录是评审结论的载体，不由运行器自动判分。
- `repair_baseline` 仅用于恢复遗漏审定文件后的原控制组复测，最多4格。spec 的
  `repair_purpose.id` 固定为 `restore-audited-seed-runtime-files`，`incident` 和
  `original_baseline_binding` 各提供 `path/sha256`。必须匹配已关闭事故、原控制组生产提交、
  四格请求/manifest/HITL、配置与账本；修复允许知识身份改变，并要求234项审定索引。
  新 `followup` 可以比较该维修基线；原 `candidate` 不能借此重开。实际分配仍受156总上限。
- `reviewed_candidate` 是2026-09-30新增明确授权的独立4格：P01/P04/P08/P02各一次，
  起点必须为127，旧相位计数必须是baseline4/candidate1/repair_baseline4/followup4，
  不能重开旧followup。spec/binding 的 `development_authorization` 提供本地凭据path/SHA；
  核对approved、相位、顺序、127→131及晋级后24→155，并在每格准入前复核文件。
  该相位对维修基线使用 `historical-baseline-different-collector-v1`：在原须相同的对照字段中，
  仅放宽runner_commit；生产提交与核心资产按各自binding分别冻结。请求、HITL、模型、
  配置、依赖、种子、来源政策和七天窗口仍须一致。历史基线与新候选
  不同时运行，不能称为同期配对实验；冻结截止取前置凭据和基线七天窗口的较早者。
  该历史分配的acceptance从131起点、四格新开发均已准入且锁定此候选。新评审锁另需
  `development_matrix` path/SHA，绑定同一候选的closed/4 planned/4 admitted/无安全停止
  矩阵和四个终态；`development_summary` 明示usable_and_supported≥3、critical_errors=0、
  no_material_regression=true、independent_review_passed=true。原始评分不由运行器推断。
  新候选与最终验收仍严格相同采集器提交；未完成或未晋级不得挪用最终24格。
- `delivery_candidate`是2026-10-01确认的新增4格，131→135；晋级后的最终24格为135→159。
  先用`python -m benchmarks.quality_selection_runtime authorize-extension --authorization <grant.json>`
  显式安装一次授权。固定字段包含旧/新上限156/159、起点131、开发4格、条件最终24格、
  原ledger identity摘要、前17条准入摘要和用户确认；安装核对实际历史，不据文件自称重置额度。
  账本追加`budget_extensions`单条记录，`.extension.json`保存独立写前见证，两者缺失/不符、
  授权文件hash变化或提交中断均停止。原identity中的156及历史binding保持可读。
  spec/binding须提供同一`budget_extension` path/SHA，freeze、collect和每格串行准入均核对。
  新开发只可比较最近reviewed_candidate的4例，历史比较仅允许runner_commit不同；其余身份、
  原请求/HITL/种子、来源政策和七天窗口不变。最终必须锁定新delivery候选、完整四格评审及
  相同生产/采集器身份；不能借旧reviewed候选锁跳过新开发。旧批次不得重开。
- 知识种子恰含 `chroma/`、`learned_docs.json`、`chunks.json`、`seed-manifest.json`。
  审定文件参与检索行为，不能当作可丢弃的构建附件。复制前后和启动时校验整树字节身份、
  审定索引数量/哈希、侧车文件哈希、SQLite完整性与文件边界；链接、待处理WAL等拒绝。
  `build-record.json` 和原始 `data/` 留在来源根，准备方先核对四项与原停止根逐字节一致。
- 前置只复用有界、通过且未过期的 receipt，并核对模型/端点哈希、配置、依赖及探测代码。
  freeze 会复制停止状态的知识种子；serve 在导入工作流前设置隔离路径。耗尽的 Tavily key
  状态沿用同一绝对路径并核对启动前哈希，禁止强制 reprobe，不重置供应商配额。
- 每批单 worker、串行、新产品/检查点库，停止根不续跑。每格在提交前保守占用额度；
  未知提交和取消不退款。原开发相位和维修基线各最多4次；新增reviewed_candidate最多4次，最终最多24次。
  原reviewed分配累计最多155/156；2026-10-01扩展后最多159，旧准入不退款、旧未提交格不重开。
  每相位只允许一个获得准入的binding：已有准入后拒绝再冻结，准入事务拒绝跨binding续记。
  所有格先写入 `matrix.json`，未提交格保留原因；`runs.jsonl`、准入、正文/快照/Markdown
  导出均分格保存。运行异常立即关闭本批，新批次先对账，不重试未知 POST。
- 普通已分类来源/模型故障及匹配终态的超时/取消按冻结矩阵保留并继续。身份、预算、
  权威、缺最终观测、未分类错误、导出不一致停止后续准入。身份端点在采集健康检查时重新核对生产/采集器提交及配置/资产。成功正文只记 `artifact_complete`
  或降级；Trace 完整性始终标为未知，来源失败及引用 unknown 计数另存，不据此自动通过内容评审。

本工具面向受控的本地评估进程；运行期间不通过其他客户端创建/重试研究，不改代码或环境。
实际矩阵、凭据、HITL正文和原始产物留在忽略区。测试使用模拟服务与合成保留形状，不读取真实保留题。

## 当前可复用能力

| 入口 | 用途与边界 |
|---|---|
| `python -m benchmarks.run_offline_eval --check-baseline` | smoke-v1固定12例，无模型/网络；只验证确定性路径 |
| `product_optimization_dev_requests.load_dev_requests` | 读取原P01/P04/P08冻结请求；不包含新协议的全部案例 |
| `python -m benchmarks.product_baseline validate` | 校验旧O1案例，不能当成新数据集已冻结 |
| `DurableBaselineCollector`及`/api/v1/tasks/*` | 已有durable研究采集与观测；复用前检查新矩阵、HITL、身份和分母兼容 |
| `python -m benchmarks.product_baseline_preflight` | 已有路由/LLM探测；会按所选模式外呼，不自动执行 |
| `python -m benchmarks.run_baseline --health-check` | 检索/Tavily检查，会消耗额度；不验证LLM或研究效果 |
| 官方source-capture/review/seed模块 | 已有来源保存、审核与种子工具；按原安全/身份契约复用，不把旧受审主题外推为通用证据 |
| `locust -f benchmarks/locustfile.py` | 只读端点负载；不是报告质量或研究吞吐验收 |

新开发请求及必答项见 `quality-selection-development-v1.json`（版本1.0.0；SHA-256 `e230c6e28e117a7e1216e6e507431a90712013dd2a51655f2396ea0525bfc3b0`）。
新保留集由独立评审封存；实现者在候选锁定前只接触其类别、版本和哈希，
不得在本工具说明中展开题目。新入口复用现有collector和数据结构，并补充本协议的绑定、调度和准入检查。
必须在首次外呼前检查新场景是否被旧case allowlist、旧停止规则或源hash锁定；有差异先
离线验收再执行，不能把新协议JSON直接交给旧CLI。不要声称不存在的新命令已经可用。

## 新批次执行约束

只走durable路径，串行、每批新目录和独立产品/检查点两库；显式绑定请求、候选/基线、
模型配置、知识种子和研究上限。报告、快照、准入、预算/Trace和只读评审结果保存在outputs。
原始.env、报告正文和trace不提交。研究中断先对账，不复用旧停止根。

用户已有范围内持续付费授权，执行开关是防误触措施，不产生每次重新询问的义务。
范围与预算未冻结时先准备；不得仅凭旧机器卡OPEN或剩余额度执行。复用兼容的前置结果，
不对每个小改动重做LLM/健康探测；具体调用上限与停止分类见质量协议。

## 历史工具与冻结文件

`product_optimization_serial_check_v1/v2/v3/v4`、`s1_qualification`、repair-pair、
PR2B及旧串并发compare的运行/阈值只绑定各自历史身份。保留代码和机器卡供审计/复算，
不直接作为新路线执行器。旧`--legacy-direct`绕过durable，不用于新产品质量结论。
旧12路并发和48格命令不再出现在默认运行说明中。

详细历史参数和使用条件见[旧工具指南](../docs/archive/quality-direction-20260929/benchmark-guide-history.md)。
旧数据/哈希/评分保持原义；本轮quality-selection-v1与300-case、smoke-v1和旧O1分母分开。


### 2026-10-01追加开发准入

`quality_selection_runtime authorize-coverage --authorization <file>`只安装明确批准的
coverage_candidate四例授权。它绑定原ledger identity、extension及135前全部准入；通过
独立表/见证追加，不改历史identity或extension。freeze/collect必须携带同一
coverage_authorization引用；仅135→139，最终24及旧相位均拒绝。此相位不支持生成最终
晋级锁。授权不等于测量完成，实际结果和163上限见维护状态；另四题仍封存。

最终禁启不依赖该授权是否已安装；当前acceptance加载、freeze、collect及reserve均拒绝。历史
binding仅可用require_current=False校验，不授予执行权。163为账面授权上限，当前只可新增4次。
