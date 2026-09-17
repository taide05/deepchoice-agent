# O1-C 真实单例验真

## 当前进展：确定性缺口离线修复，真实复测未授权

2026-09-17 用户授权离线定位及有回归测试的最小修复，不自动补跑。明确区分：

- **产品缺陷**：旧来源评估没有显式候选准入；把所有其他高分 URL 当互证，抬高 strong；
  Tavily 的 `\N` 原样进入证据；What/Why/How 用任意标题词片段给声明补 Sources，
  例如 `On` 可把无关论文附到 PostgreSQL 文案。合成 sanitizer 另会截断含标点/括号的真实标题。
- **不是已确认的词法误判**：P01 的 53 处检查实际为 30 network_uncertain、19 url_invalid
  （本地 file://）、4 citation_missing；没有 lexical_mismatch。其中三个分号前子句未带引用，
  另一处为推荐末句未引；不把尾部引用自动移给前句。
- **安全获取边界**：本轮 official 选 local-proxy；按候选代码，动态 safe-fetch 不接受不能固定
  已验证 IP 的 proxy/forward，因而可产生 network_uncertain。原件未保存异常细分类，不能
  将每个 unknown 的个别原因都倒推确定；不绕过安全策略、不以搜索片段冒充实时验证。

修复契约：有 `task.candidate_techs` 时，标题/摘要须词法提及至少一个显式候选才进入评分；
保留原始检索结果和失败状态，无候选/类别任务不猜词。共享候选名不构成主张互证，
`supporting_sources` 不再凭分数/数量填充。缺失标题使用 `Untitled source (<URL hash>)`，
只标元数据缺失、不编造题名。来源链接只按显式且唯一的标题引用展示，无引用/歧义不补链。
平衡括号的语法解析在合成、验证与渲染间复用，多引用只在最外层拆分；合成清洗和
链接展示保留 C++ / C# / node.js 等标点。引用验证的支持判断和四状态规则不变，
其 v1 注册表仍有简化标题/子串匹配盲区，本轮不声称全面精确绑定或语义证明。

新运行冻结 `source-score-v2` / `what-why-how-v2`；旧 v1 manifest 身份仍可读，
same-run resume 拒绝跨版本。schema、Prompt、冻结案例、路由、预算和重试策略不改。
回归覆盖见 `tests/test_o1c_evidence_cleanup.py`。P01 原件离线复算分母为 27 个来源，
准入 13、排除 14、strong 0；旧报告/快照未改，也未运行合成模型，不是新的质量/成本对照。
仍会保留提及 PostgreSQL 的 Redis/Neo4j 等相邻比较，词法门不是语义相关性证明。

smoke-v1 fixture/指标/门槛不变且 12/12：模板不再猜测补链，只有 RP-001 报告 hash 变化，
连同 registry/manifest/时间及指纹更新确定性基线；来源健康仍 not_run。
新指纹 `6d57e84daa93ed8473116dfca2fb171da367883e62e4fc1a76d40c87753210f2`。
最终 Windows/Python 3.12.4 离线验收：167 聚焦通过（20.20 秒）、1271 全套通过、
0 skipped（212.38 秒）；smoke-v1 12/12 且新基线匹配，pyflakes src/tests/benchmarks、
vulture 100%、pip check、diff 检查通过。独立只读复审的两项标点/嵌套解析发现已修正，
复审者离线断言确认闭环，无剩余阻断；未重跑全套或验证真实质量。原报告/快照 hash 未变。
本轮测试临时目录清理，全部实测原件保留。没有新增真实调用，额度保持 44/48；
下一步只可另行确认一次新 run 单例复测，不恢复 D/E/O2 或批次。以下保留原运行事实。

## 实测结论：P01 冷启完成，质量与批次资格未通过

2026-09-17 用户重新授权前置并确认执行 P01 一次。仅创建 1 个 run，无重新提交、恢复、
批次或保留集访问；累计 **44/48**，剩余 4。研究状态 completed、报告可取、无需 HITL，
但报告仍有明显缺陷；本次不是 O1 闭环、稳定性保证或串并发门禁通过。

### 冻结身份与执行条件

- 代码审计身份 `d451b49138558f2c5ebd86f50772c1c70709c4a5`；最近生产改动
  `dddc036781a3630b5b73971a08199e5e47284be2`。数据集 product-baseline-v1 / 1.0.0，
  冻结日期 2026-09-16，hash 同下方历史记录；分母为 P01 × 单例 × 1 次。
- manifest `ed3821f00026bb881df626e2e97c5c2706d0074ce9f0c50c22d41bf567da4b01`；
  core registry `8918c0fd30e14ab9888b6e6472486d1da0c8a8601337c12e803e704b14d65d7c`；
  environment `d6d843ec0145fe1aab3af9f49c5b571ce2aa6a9dbd3c7a004fae661539889fc5`。
- Python 3.12.4、请求模型 deepseek-v4-flash、thinking disabled、线程上限 1、离线模型下载，
  新空产品/检查点数据库对、只读知识副本、缓存开启；没有预热。冻结知识 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。
- 准备时 SQLite backup 改变了知识库头部偏移 27/43/95，物理 hash 校验停止，尚未提交研究。
  两份 DB 完整性通过；失败副本保留，将未使用的实验副本恢复为原冻结文件逐字节拷贝，
  重新验证全部知识 hash 和空运行目录后冻结环境。原知识库与生产复制逻辑未修改。
- 研究准入 12:52:11 UTC，采集结束 12:53:44 UTC；默认硬预算 60,000 token / 96 LLM /
  72 retrieval / 900,000 active ms 不变，auto-recovery 仅在隔离服务关闭。

### 已知结果与成本（2026-09-17，分母 1 run）

- Wall 93,140 ms，预算 active 90,900 ms；27 LLM、13 retrieval，共 40 个逻辑外部调用，
  failed calls / LLM retries / node retries 均 0。逻辑调用数不是实际 HTTP 尝试总量。
- 六源状态 success 6/6，结果数 tavily 7 / chroma 4 / github 7 / arxiv 7 / community 0 /
  official 2；partial_failures 空。community 零结果不等于提供了有效证据，也不证明并发限流已解决。
- 输入 21,039、输出 3,159、合计 **24,198 token**；27/27 usage 和缓存拆账完整。
  输入 cache hit 5,760 / miss 15,279，命中率 27.38%，未命中占输入 72.62%。
  冲突检测 miss 7,399、结论合成 miss 5,812，合计占 miss 86.46%。价格 unavailable，
  金额 unknown；这些数不含前置探测/健康检查，不是完整账单或节省证明。
- 输出诊断覆盖 27/27、finish_reason 已知 27/27，无截断；JSON strict 25/25，浅层 schema
  valid 22/22。repair_attempts 25 是兼容 parser 调用次数，不是 25 次坏 JSON；另 3 次 JSON
  没有 schema 检查，采集器整体 qualification 仍 not_evaluated，不把这些分母合并。
- Embedding 12:52:19 UTC 开始，冷加载 **4,906 ms**。78 个约 2 秒间隔的健康/内存样本均
  HTTP 200、authority_valid；实例最大心跳间隔 19,766 ms，实例/运行最大续期
  9,375 / 9,469 ms，运行最大 schedule lag 312 ms，运行 heartbeat failure / lease loss 均 0。
  采样不是连续无故障证明。服务峰值 working set 1,801,977,856 bytes（约 1.68 GiB），
  主机最低可用内存 497,569,792 bytes（约 475 MiB）；仍有内存余量风险，既往蓝屏/WHEA
  根因未解决。本轮未观测到重启，不能宣称硬件稳定。

### 报告核对与停止线

报告读取核对发现：无关仓库/论文混入证据与引用列表、来源标题出现 `\N`、结论 high confidence。
确定性引用检查共 53 处：verified 0 / unsupported 23 / unreachable 0 / unknown 30；
这是系统词法/可达性投影，不是助手逐原子声明的语义评分，unknown 不等于错误。
报告内容质量尚未正式按 v4 台账复核，本次不填最终 rubric 分数、不与旧候选六份报告拼表。

隔离服务 12:54:18 UTC 正常退出，观测器退出，所属进程和端口均已关闭；全部本地原件保留。
下一步仍在 O1：优先离线追踪本报告的无关来源、异常标题与声明/引用绑定，再决定最小修复；
不自动改 Prompt、冻结案例或预算，不补跑 P01，不启动 D/E/O2 或整组串行/12-case 并发。

原件位于 `outputs/o1c-single-20260917/` 与 `outputs/o1c-control-20260917/`，不提交 Git。
SHA256：experiment.json `24b624ac0650e28c4c294379ff04217aa07a68e1f5147dc84fbda3345c2a05dd`；
runs.jsonl `d1865efa93bc67a607ccd8661dfdad24b8cd4e9bf714b754bdd25f9fb064850f`；
P01.md `2013306bb116a8349e17bd09096e7cb8fd508dd5c7472a5e128254fb9c112c3e`；
P01.json `fea087e895e6b6a6cf76946487f110c8bc389608c7ed31e47b1cd50f43d824f0`；
health-memory.jsonl `90e79dd2d09bc368e85dc5cc675783ca2c147e2778057f56a5e0078acdf98d09`；
cold-start.jsonl `1cebe02d9c1441a097ab3433cbcb38a46347fd4e2aa589c6cca4236bfa1da174`。
本轮未改生产代码或测试；既往同生产候选 1244 全套 / smoke 12/12 与静态验收仍有效，
仅新增真实单例观察与文档核对，不重复未变更全套。以下保留先前失败，不倒填原件。

## 历史：首次前置停止

日期：2026-09-17。状态：**preflight_stopped，单例未执行，O1 仍 incomplete**。
随后用户授权定位两项阻断，见 [诊断记录](o1c-blocker-diagnosis.md)：新社区单源反馈确认
throttle_violation，并发现 probe 未带已配置的可选 key；离线时间断言存在时钟/打点契约错位。
后续诊断不倒填本次原件，也未修复或继续研究。
用户授权先验真一例；按任务卡选开发例 P01，最多一次提交，不重复、不自动恢复、不跑批次。
本轮未修改产品、测试、冻结案例、Prompt、路由或预算。

## 实际观察

- 执行候选：`51c7c21083da75e8411c1cb062df15a85c3f6322`（O1-B 已验收版本）。
- 数据集：product-baseline-v1 / 1.0.0 / 2026-09-16，SHA256
  `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`。
- 一次真实检索前置检查，完成时间 2026-09-17 11:50:35.350290 UTC（北京时间 19:50:35）。
  五个网络来源健康项 **4/5 通过**：tavily/github/arxiv/official 为 local-proxy；
  community 选中 self-forward，但 `ok=false`。另行 routed Tavily 搜索 POST 通过。
  这不是研究六源的成功率：本地 ChromaKB 未测，研究内六源状态均 not_run。
- LLM/Tavily/GitHub 凭据存在检查通过，但不等于 LLM 连通或输出资格通过。
  LLM 探测、冷模型初始化、隔离服务、研究提交、报告、缓存 token 拆账均 **not_run**。
- 新建研究 run **0**，累计仍 **43/48**、剩余 5。健康检查已发生真实网络请求及 Tavily 搜索，
  其费用/重试总量未完整采集，金额 unknown；不能写成“本轮零费用”。无研究 token 观察。
- 主机前置可用内存约 2.9 GiB；读取到两条既往 WHEA-Logger 18（09-16 15:30、15:48）。
  没有真实研究峰值、心跳或冷启耗时样本；这些前置事实不证明硬件稳定或已修复。

## 阻断解释与证据边界

`outbound/resolver.py:health_check()` 仅在探测接受某通道后返回该 channel；当 provider gate
`unavailable()` 时仍保留 channel、把 `ok` 置 false 并标为 rate_limited。
`throttle.py:unavailable()` 表示已记录限流或冷却未结束；社区的反馈可来自 HTTP 429、
throttle_violation 或成功响应中的 backoff（见 `probe.py:ok_for()`、`throttle.py:observe()`）。

因此，**按冻结候选代码推断，此次 community 属 provider gate 不可用，不是转发断线的证据**。
安全检查产物只保留 ok/channel，未保留原 status、HTTP 状态、backoff/Retry-After；
具体触发原因与冷却期限 unavailable，不能断言实际收到 429，也不能判定限流补修无效。
下一次授权检查应保留 allowlisted status/安全限流分类，不保留响应正文、私有 URL 或凭据。

原件（本地保留、不提交 Git）：`outputs/o1c-control-20260917/retrieval-preflight.json`，SHA256
`6c88ef73320f591be26f438a0b77e3f97ecc691d0cc42e33dae3ae5b6b3e5e31`；
执行 helper `check-health.py` SHA256
`6f7795e9013e16d66823e3935da75788bc3d5e9aaa03ec42f4ea248ec9f7cc0f`。
脱敏事实投影见 [JSON 记录](o1c-preflight-observation.json)。未创建 `outputs/o1c-live-20260917`。

## 后续动作 / 停止线

1. 保留这次失败，不自动重跑健康、切路由、绕过冷却或提交 P01；没有进入 O1-D/O2。
2. 下一步先确认 community 可用性与安全限流反馈；若需改代码，另做有测试的最小修复。
3. 前置恢复后，重新明确授权 P01 一次提交，使用新空数据库对、同一知识快照与冻结预算；
   继续检查六源失败、缓存拆账、JSON/结构、冷启/心跳。再次失败或降级仍停止。
4. 单例成功只支持该例执行观察；不代表语义质量、硬件稳定、12-case 并发或 O1 闭环通过。

验证：O1-B 的 1238 全套通过（0 skipped）及 smoke 12/12 是该未变更候选的既往验收，
不是本轮全绿声明。本轮 outbound/限流离线回归 **53 passed / 1 failed**（22.25 秒）；
失败项 `test_mocked_twelve_cases_retain_six_source_results` 的缩放毫秒级请求间隔断言失败，
此前六源结果一致性断言通过。仅该项独立复查 **1 passed**（19.06 秒），不覆盖首次失败，
不据此确认根因或宣称 flaky 已修复。该测试完全使用合成 HTTP/本地 fixture，未调用真实服务。
JSON 原件哈希、脱敏投影、4/5 分母、无新研究目录及 git diff 检查通过；未产生测试临时目录。
本轮只补文档/事实投影，未改代码/测试；不重复未变更全套。后续应先定位这一时序不稳定，
修复后按契约跑聚焦和全套，再考虑真实单例准入。O1-C 不能呈现为完成或当前验证全绿。
