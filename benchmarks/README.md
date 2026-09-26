# 评估入口与历史工具

更新：2026-09-24。本文是工具操作说明，不是任务授权或当前运行状态。正式产品效果协议见 [产品效果优化](../docs/product-effectiveness-optimization.md)，
准备检查结果见 [基线准备检查](../docs/baseline-readiness-audit.md)。

| 入口 | 用途和边界 |
|---|---|
| `python -m benchmarks.run_offline_eval --check-baseline` | 固定 smoke-v1 的 12 例，无 LLM/网络；只验证确定性路径 |
| `evidence_window_prototype.select_evidence_window` | 未推广的纯离线定位原型；输出全部不可绑定，不被默认研究路径调用。反例与限制见 S0 诊断，不作质量/成本评估器 |
| `product_optimization_dev_requests.load_dev_requests` | 只读固定 P01/P04/P08 开发请求投影；不打开完整案例集或保留集 |
| `product_optimization_official_intake.load_official_intake_plan` | 只读固定 v3 计划中的15个 P01/P04/P08 精确官方深链 locator，并校验开发请求、v1/v2历史身份与93根目录身份；不读取正文/报告/保留集，locator 不等于来源批准 |
| `product_optimization_source_capture.capture_official_target` | 仅以冻结 target ID 经 direct 安全外呼抓取一个精确 URL；本地 route admission 不探测第二站点，禁止重定向并要求最终 URL 完全一致，30秒/2MiB有界，原子保存到忽略目录且只标为未批准候选 |
| `product_optimization_source_review.load_approved_source_review` | 对 tracked review 绑定的15份 exact receipt/body 做纯离线 fail-closed 审计，输出限定主题的一方官方证据；不把第一方产品文档提升为独立性能、可靠性、成本或通用胜负证据 |
| `product_optimization_seed_builder.build_frozen_seed` | 从已批准正文构建固定 ignored 目录中的隔离 Chroma seed；BGE-M3 绑定 commit、`local_files_only`、234个有界 chunk，并经哈希一致的未打开副本原子发布；拒绝覆盖，不读取旧库或保留集 |
| `product_optimization_seed.load_and_validate_seed_manifest` | 纯离线检查有界 UTF-8 输入与固定身份/已知模板标记；自报 URL/发布者不构成来源批准 |
| `python -m benchmarks.product_baseline validate` | 校验 O1 的 12 例版本化案例集，不调用 LLM/网络 |
| `python -m benchmarks.product_baseline collect ...` | 经 durable API 采集 serial=1 或 concurrent=12 的真实结果；必须冻结案例和环境，并显式确认付费运行 |
| `python -m benchmarks.product_baseline collect-single --case-id P06 ...` | 仅一个开发 case、concurrency=1、新输出目录及付费开关；运行可靠性验证，不是完整基线 |
| `python -m benchmarks.product_baseline compare ...` | 对按该批冻结协议完成评分的同 repetition 串并发结果执行历史质量门禁，无网络调用；不替代新 GPT-only 路线的执行器 |
| `python -m benchmarks.run_baseline --health-check` | 检索路由与 Tavily 连通性，会消耗 Tavily 额度；不检查 LLM，也不证明研究完成 |
| `/api/v1/tasks/*` | 当前产品路径；真实基线须经此入口采集任务、报告、HITL 和 observability |
| `python -m benchmarks.run_baseline --legacy-direct ...` | 保留的历史直连实验，不经过 durable RunContext，不能用于新产品基线；会调用付费 LLM 与 judge |
| `locust -f benchmarks/locustfile.py` | 只读 health/docs/durable 查询负载，不创建研究、不衡量报告质量或研究吞吐 |
| `.github/workflows/benchmark.yml` | 手动离线 smoke；已移除旧付费 runner 和固定 Top-1 门槛 |

O1 的 12 例及[官方参考依据](../docs/o1-reference-audit.md)已冻结为 1.0.0。
当前候选/研究计数以 [执行状态](../docs/o1-execution-status.md)为准；任务与新的验证范围以
[整体地图](../docs/current-roadmap.md)为准。以下命令仅在相应冻结执行卡覆盖时使用，不能从历史 48-run 批准推定新批次授权。
正式实验进度及主机风险见[执行断点](../docs/o1-execution-status.md)。候选状态、未通过检索健康或 LLM 兼容检查时，采集器会在
任何研究调用前停止。LLM 检查需覆盖 JSON、工具调用与实际使用的 thinking 配置；全量测试不
代替此项。

S1 协议文件为
[product-optimization-s1-constraint-aware-v2.json](product-optimization-s1-constraint-aware-v2.json)，
冻结 SHA-256 为 21f561408e7bbaabd057785df685cf36a0271709d92cacc522ff5ac289625f65。
使用 python -m benchmarks.product_optimization_s1 可纯离线检查当前 candidate 工作树；
baseline 执行 ref 使用 --execution-arm baseline --execution-ref 814131f849f417fbcf4f00cfe071d95ccf2b3878。
指定 ref 只检查已提交对象；实际运行仍须由环境清单记录干净工作树的完整 commit。
校验不等于资格、health 或付费执行通过。
原 v1 文件/hash 保持不变；可显式 --protocol benchmarks/product-optimization-s1-constraint-aware-v1.json
并指定原候选 --execution-ref bcb4c8732e94b5aac4a3645b7d5d682279e2dad0 复算，不将历史资格
用于新身份。v2 从 91/134 起算，至多 1 次资格 + 12 格正式比较，保留最终验收 24 次及余量 6 次。

S1 单例资格使用 python -m scripts.s1_qualification，按 audit → preflight → prepare → run
顺序执行，同一 --root 指向全新的本地研究目录，--env-file 指向私有配置；audit 只核对身份、
依赖、路由和模型，无网络调用。preflight 需要 --execute-paid-probes，至多一轮冻结前置；
prepare 需要 --frozen-seed，按原知识哈希复制至隔离目录；run 需要 --execute-paid-run，
只允许 P01/serial/一次准入，遇 HITL 不自动回答、取消或恢复。前置或控制器身份变化、旧根
重跑、来源/HTTP/authority/预算异常均关闭后续准入，不自动补跑。

原协议的 controller source_objects 绑定五个采集/资格基础模块，不是整个可运行控制链。
此入口另用本地 preflight-binding.json 和 s1-execution-binding.json 绑定干净完整 Git 身份、
三个运行脚本、环境文件及前置证据哈希；协议、产品候选与停止阈值不变。执行成功仅表示可供
内容资格评审，formal_measurement_gate 仍为 closed。本入口不执行十二格局部配对；旧 PR2B
整批命令也不能代替双产品配对执行器。所有原始运行记录留在 outputs/。
其中 git_commit 表示实际执行 checkout（包含工具和文档），不是另一个产品候选；产品身份
由严格固定的 protocol_sha256 引用 candidate.anchor_commit=83852d8 及 source_objects，
并在执行前将 HEAD 产品对象逐一与其比较。只改工具/文档不能绕过该产品字节校验。

隔离实验服务使用独立产品/检查点数据库；知识库与 learned-docs 快照必须显式指定，不能复用
日常写入目录冒充冷启动：

```powershell
$env:DEEPCHOICE_EXPERIMENT_DIR = "outputs/product-baseline-v1/serial-r1-runtime"
$env:CHROMA_PATH = "<只读知识库快照路径>"
$env:LEARNED_DOCS_PATH = "<learned-docs 快照路径>"
$env:LEARNED_DOCS_READONLY = "1"
.\.venv\Scripts\python.exe -m uvicorn benchmarks.product_baseline_server:create_app --factory --workers 1
```

另一个终端先校验候选集。操作者核验并将案例标为 `frozen`、填写私有环境 manifest 且两项健康
检查为 `passed`、确认对应实验的剩余额度和运行矩阵后，才可添加显式执行开关：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.product_baseline validate
.\.venv\Scripts\python.exe -m benchmarks.product_baseline collect --profile serial --concurrency 1 --repetition 1 --environment-file <环境清单.json> --output-dir outputs/product-baseline-v1/serial-r1 --execute-paid-runs
.\.venv\Scripts\python.exe -m benchmarks.product_baseline collect --profile concurrent --concurrency 12 --repetition 1 --environment-file <环境清单.json> --output-dir outputs/product-baseline-v1/concurrent-r1 --execute-paid-runs
.\.venv\Scripts\python.exe -m benchmarks.product_baseline compare --serial-dir outputs/product-baseline-v1/serial-r1 --concurrent-dir outputs/product-baseline-v1/concurrent-r1 --output outputs/product-baseline-v1/concurrency-r1.json
```

每次 profile 使用新的 `*-runtime` 数据库目录和单独的新采集输出目录。`scores.csv` 必须先按该批次
冻结的评审协议完成盲评，比较命令才会运行；现行新路线采用 GPT-only，且须另冻协议和双臂执行器，
不能把这个旧入口直接当成新测量。

`admissions.jsonl` 在 POST 前及确认创建后立即保存并 fsync；重启先核对它，未写完的 run 不能
自动重建。`usage.csv` 逐 case 导出已知 token/完整性与调用数；未知为空，不是零。报告和 snapshot
分别存入 development / holdout 子目录；保留集在候选锁定前不查看。比较需同环境 hash、代码提交、
数据集 hash 和配对 manifest，评分必须绑定实验/run 并有 reviewer/evidence_notes；缺报告不判通过。

以下探测不创建研究任务，输出目录必须为新文件；routes 仅做 credential-free 路由检查，
不能替代上述包含 Tavily POST 的完整检索 health-check：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_preflight --mode routes --output <路由检查.json>
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_preflight --output <模型检查.json> --execute-paid-probes
```
第二次 repetition 使用 `serial-r2` / `concurrent-r2`；两次均通过才算并发效果门禁通过。

## O1-PR1 单例资格

以下为单轮资格工具的操作入口；只有该轮已在执行卡范围内才可调用，不能循环使用。一轮路由汇总降级后停止付费探测；
沿用既定 resolver 候选通道选择，禁止重新执行整轮。只有全部通过才能离线 prepare。
输出目录必须不存在，工作树必须干净。前置 journal 在 dispatch 前 fsync，保守计入 forward
carrier HTTP，但不会将 carrier POST 误计为 Tavily 付费 POST；隐式代理 CONNECT 不在该计数中。
准备成本单列，JSON/工具各最多一次且禁用 SDK 重试，实际 LLM 总上限 4。
`--trust-current-local-proxy` 只对当前实验进程选择严格固定本地代理，不修改 `.env`。

```powershell
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_qualification preflight --output-dir <新前置目录> --trust-current-local-proxy --execute-paid-probes
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_qualification prepare --output-dir <新实验目录> --preflight-dir <本轮前置目录> --frozen-seed <已验证无WAL种子> --expected-knowledge-sha256 <冻结树hash> --trust-current-local-proxy
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_experiment serve --root <新实验目录> --profile serial-r1 --embedding-startup-mode cold-in-research
.\.venv\Scripts\python.exe -m benchmarks.product_baseline collect-single --case-id P01 --repetition 1 --environment-file <新实验目录/environment.json> --output-dir <新采集目录> --api-base http://127.0.0.1:8011 --execute-paid-runs --stop-at-hitl
```

serve 与 collector 进程须显式继承相同的可信代理配置；一个 CLI 子进程的 opt-in 不会传回
父 shell，可由经审核的本地控制器逐进程设置。启动检查该 hash 和冷启策略。默认 serve 仍预热，
默认 collect-single/collect 仍执行冻结 HITL 策略。资格模式等待 HITL 即停，禁止自动动作、
重试或恢复；原始报告、Trace 和资源/实际 CONNECT/TLS 观测留本地。
前置与 completed 不能单独证明资格，完整报告声明核对和独立复核见
[资格证据](../docs/o1c-single-case-verification.md)。未覆盖的实际动态 TLS 保持 unavailable；不额外外呼补测。

## 已停止的修复包局部12格（v3）

`product-optimization-repair-pair-v3` 只包含 P01/P04/P08，不读取完整数据集正文或 P09–P12。
它的唯一正式执行已在 baseline-r2/P04 完成后按 `strict_safe_fetch_failure` 停止：1格 completed、
11格 not_submitted、无提交不确定性。下列命令仅记录冻结操作界面，**不得再次执行、换根补样或与
v1/v2 拼接**；后续工作必须先完成三次付费停止后的测量复议并冻结新身份。
协议外批准 byte SHA 为
`47bfeffa01893b6077a480b06dd6ff4254d6c121d110614747a3fc2f9db9c268`；每个命令都必须显式传入，
不能从协议自身推导后自动接受。先在已提交且批准路径干净的 candidate 与只读 baseline checkout 上
执行零网络 `audit`。`preflight` 才会做有界付费探测，`run` 才会提交研究任务：

```powershell
$protocolSha = "47bfeffa01893b6077a480b06dd6ff4254d6c121d110614747a3fc2f9db9c268"
$baselineRoot = "<只读 d23c948 checkout>"
$candidateRoot = "<当前干净 checkout>"
$privateEnv = "<私有 .env 绝对路径>"

.\.venv\Scripts\python.exe -m scripts.product_optimization_repair_pair audit --baseline-root $baselineRoot --candidate-root $candidateRoot --env-file $privateEnv --expected-protocol-byte-sha256 $protocolSha
.\.venv\Scripts\python.exe -m scripts.product_optimization_repair_pair preflight --baseline-root $baselineRoot --candidate-root $candidateRoot --env-file $privateEnv --output-dir <新前置目录> --expected-protocol-byte-sha256 $protocolSha --trust-current-local-proxy --execute-paid-probes
.\.venv\Scripts\python.exe -m scripts.product_optimization_repair_pair prepare --baseline-root $baselineRoot --candidate-root $candidateRoot --env-file $privateEnv --preflight-dir <本轮前置目录> --experiment-root <新实验目录> --expected-protocol-byte-sha256 $protocolSha
.\.venv\Scripts\python.exe -m scripts.product_optimization_repair_pair run --baseline-root $baselineRoot --candidate-root $candidateRoot --env-file $privateEnv --preflight-dir <本轮前置目录> --experiment-root <新实验目录> --expected-protocol-byte-sha256 $protocolSha --execute-paid-runs
```

顺序固定为 baseline-r2、candidate-r2、candidate-r1、baseline-r1，每块 P01/P04/P08，共12格且
`concurrency=1`。只有 citation verifier 专属 provenance 下的已知 safe-fetch 策略/传输失败，才在
终态和来源门禁完整时可降级为
`unknown` 后继续；`safety_rejected`、429、普通5xx、检索、预算、租约、身份或未分类异常仍会停止
新准入。已尝试格不重试、不补样、不跨根拼接。全局 ledger 位于忽略区
`outputs/product-optimization-ledgers/product-optimization-repair-pair-v3/`。v3 前向绑定已停止的 v2 claim、
唯一完成的 baseline-r2/P04 cell、observation 与 result；旧 `...repair-pair-v1/` 和
`...repair-pair-v2/` 必须原样保留。任一命名空间的文件都不能删除或改写为允许重跑；v3 只有一次
完整执行机会，累计预算固定为94＋12＋48＝154；实际停止后累计研究为95，最终/并发48仍未动。
`audit`/`prepare` 通过只代表离线控制契约；内容改善须等12格完整报告按冻结盲评协议评审。

## 冻结的修复包局部12格协议（v4）

`product-optimization-repair-pair-v4` 是测量复议后的前瞻协议。它绑定
d23c948 baseline、d7e776d candidate、原12格顺序/种子/评分门槛，以及v1、v2、v3三个不可变
停止根。新增控制信息仅为 `safe_fetch_phase` 和三个明确的HTTPX response-stream生命周期类型；
只有citation safe-fetch已进入HTTP dispatch且终态/来源门禁完整时才可继续保留citation unknown。
非citation、dispatch前、`OtherError`、普通5xx、429、安全、身份、预算、租约及其他未分类错误仍停线。

用户已明确批准累计上限154→155；协议现为`frozen`、`open-after-offline-runner-acceptance`，
当前研究累计95/155，局部12格与最终/并发48格均完整锁定。未批准状态仍由runner在任何付费
preflight、prepare或run写入前拒绝。提交后零研究`audit`曾用提案byte SHA
`1dcc06ed63a7beed4a99823ddd8c3c412612806db1ffb7b0273ecdf0261724b3`通过，
`research_runs_submitted=0`；它只标识已退役的关闭准入状态。激活后的冻结byte SHA为
`dd6814e128c9e40b7b4f70b6a2b1e6db2434f4243876e783f5a20a1a25a3a6c6`。激活验收、本地提交
`b656c24`和提交后零研究audit均已通过，后者再次确认批准种子、双臂及前任身份且
`research_runs_submitted=0`。下一步是单独执行有界付费preflight；通过后才可离线prepare并一次性执行
冻结12格。不得用v4解释或拼接历史v3的两个`OtherError`。

2026-09-26实际执行中，v4 preflight通过（8 HTTP、2 LLM、1 Tavily POST，零研究提交），离线prepare
冻结4块。一次性run完成baseline-r2/P04后因`TELEMETRY_strict_safe_fetch_failure`停线：4条citation
`UnsafeUrlError/response_rejected`属于已知策略失败，另2条在`response_received`阶段仍为`OtherError`。
其余11格未提交，累计用量96/155；该根不可重试、续跑或拼接，也不能形成配对。任何替代执行须先完成
新的安全/测量复议并使用新协议、身份和账本。

## 冻结的修复包局部12格协议（v5）

零模型、零研究诊断已把 v4 的两条 post-response `OtherError` 精确识别为
`httpx.DecodingError`；另4条仍是既有`UnsafeUrlError/response_rejected`，且TLS、证书和主机名
检查均成功。v4 不因此重标或复用。`product-optimization-repair-pair-v5` 是薄控制适配器，只在
`http_dispatch`或`response_received`阶段把`DecodingError`与既有`StreamError`归一为同一
脱敏`response_rejected`；其他RequestError及全部原停止线保持不变。

v5 使用`RP5-*`盲标签、独立`outputs/product-optimization-ledgers/product-optimization-repair-pair-v5/`
账本，并精确绑定v4 claim/cell/observation/result/telemetry。用户已批准累计上限155→156；当前
96/156，局部12格与最终/并发48格完整锁定且无补跑余量。协议byte SHA为
`13e8bd9ef2e6877c4c8465db22c3ab0bc1b11f3f386e704b7b314a45ef0fd796`。离线验收及提交`0c4edec`
后的零研究audit均已通过，`research_runs_submitted=0`。随后preflight与prepare通过，正式根只完成
baseline-r2/P04：安全遥测无异常，但Chroma在当前块运行中改写3个同长度持久化文件，下一格前的
完整seed哈希复核触发`prepared block drift`；父结果同时丢失已落盘完成record。append-only ledger
仍确定只提交1格，累计97/156。v5曾使用`scripts.product_optimization_repair_pair_v5`按
audit→preflight→prepare→run顺序执行；该执行身份现已耗尽，**不得再次执行这些命令**。
历史v1–v5根均不可重试、续跑或拼接。

## 串行产品效果12格协议（v6）

`product-optimization-repair-pair-v6`是v5停止证据上的最小控制层提案，不改变产品、案例、顺序、
种子起点、单run预算、来源/安全门禁或内容门槛。它只允许**已尝试块**中的
`chroma.sqlite3`、对应segment的`data_level0.bin`和`length.bin`在文件清单与各自大小不变时产生
运行态内容漂移；未尝试块和其他文件仍须与冻结seed完整一致。若后续控制检查失败，只有同一实验根
中的append-only observation与collection record在experiment/case/task/run身份上唯一匹配，且原
`_record_stop_reason`门禁接受时，才可恢复父结果遗漏的已完成record。

本协议固定`serial-concurrency-1`，并发研究授权为0。用户随后把并发测试从当前及近期产品目标中
移除；不再冻结并发协议、设置并发门槛或预留研究格。97/156实耗下，本协议原计划最多12格；
旧48格最终/并发整合方案仅为历史规划。首次preflight的检索与Tavily通过，但协议bootstrap先于私有环境安装，LLM配置缓存空凭据，
因此在HTTP dispatch前以`OpenAIError`停止；LLM尝试0、研究提交0，该根不得复用。v6入口现先安装
私有环境，再加载协议和项目模块。冻结协议byte SHA为
`393dd11655b92d8e35683bdcbfdac1fe683f5df63ecc99a59dfdd0a7a0ceb64c`。离线验收为14项v6聚焦、
394项相关、2095项全套（117.86秒）、smoke-v1 12/12基准一致及pyflakes/vulture/pip/compile检查。
提交`e05bb6b`后的零研究audit通过。新的preflight通过后，正式根串行完成baseline-r2的P04/P01/P08，
任务3/3完成、59/59个LLM/检索Trace调用成功、0超时/重试/部分失败；wall为114.1/50.8/45.5秒，
首例包含73.6秒embedding冷启动。产品质量未通过：三例citation verified均为0，P04报告明显偏短，
P08在关键约束缺失时仍强制Winner。P08两条citation pre-HTTP安全拒绝触发正确停线，最终为
3 completed + 9 not_submitted，累计100/156。v6不可续跑、重试或拼接；余56格未分配，当前没有
开放的付费后继协议。

## 有意使用历史直连工具

仅在明确批准历史实验及调用额度后，使用项目 Python 3.11/3.12 环境：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_baseline --legacy-direct --output-dir outputs\legacy-experiment-UNIQUE --cases-file benchmarks\annotated_cases.json --cases 1
```

`--output-dir` 必须不存在；每次创建新目录，拒绝覆盖之前结果。CLI 在任何探测和研究调用前
检查模式与目录。程序级 `run_single_case/run_baseline/merge_all_batches` 保留给已知旧调用方，
不是自动安全门；新消费者不得使用它们。新生成的原始条目/报告标记 `legacy-direct-graph`。
不要将旧 runner 的成功率、缓存/预算表现、token 汇总当作 durable 测量：失败运行的用量可能
不完整，合并还可能重新调用 judge；新测量必须使用公开观测字段，未知量不得填零。

`--profile-agents` 仅保留参数兼容，节点计时本已开启。`--debug-dump-dir` 输出脱敏 hash、
长度和用量，不输出完整 Prompt/响应；case/tag 的目录文件名使用 hash，不能由 case 文本越界。
诊断目录同样必须不存在，避免覆盖历史记录；runner 的 verbose 进度只输出案例 hash 和 query 长度。
上述参数名保持兼容，但帮助文本已纠正。

## 停用但保留定位的旧入口

已批准的 O1 私有实验可用 `product_baseline_experiment prepare --root <新实验目录> --llm-evidence <探测证据.json> --execute-paid-health-check`
制作同一知识种子和四份初始副本；它保存依赖/健康/非敏感环境清单，不复制 `.env`。`serve --root <实验目录> --profile serial-r1`
在生产模块导入前设置独立知识与数据库路径，离线预热已有 BGE-M3 缓存后启动单 worker。
每个 profile 只能从空 runtime 启动；已有数据必须核对，不能直接重新 serve 冒充新实验。
实验 factory 禁止 coordinator 自动恢复（正常产品默认保留）；采集持续检查公开实例健康和重入队，停止时保留非最终用量下界。单次验证示例：`python -m benchmarks.product_baseline collect-single --case-id P06 --repetition 1 --environment-file <ready.json> --output-dir <新目录> --api-base http://127.0.0.1:8011 --execute-paid-runs`。单次工具不应自行循环提交；批量顺序及是否衔接由冻结执行卡控制，已授权的正常衔接无需再次询问。历史观察见 [O1-R](../docs/o1r-single-case-reliability.md)。

- `run_all_batches.ps1`：原先会删除批次结果，现仅说明停用并非零退出。
- `run_batch_comparison.sh`：原先绑定个人 Python 路径、吞失败并复制 latest 文件，现同样停用。
- `generate_200_cases.py`：原先导入即覆盖数据并继承跨场景答案；现导入无副作用、CLI 停用。
- `merge_checkpoints.py` CLI 与 `run_baseline --merge`：固定历史文件/案例假设、偏向成功重试、
  且可能调用付费 judge，现拒绝运行。合并实现保留审计，不作为当前指标口径。

旧实现可从 Git 历史恢复，未删除任何案例文件或已有运行结果。历史 300-case（2026-08-31）
和 Qwen adaptation 数字均保持原记录；在新代码/模型上重跑旧问题会产生新实验，不能重现当时数字。
