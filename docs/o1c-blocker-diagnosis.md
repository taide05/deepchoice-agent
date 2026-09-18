# O1-C 阻断诊断

## 最新诊断：arxiv 当前单源通过，旧限流细因未确定

2026-09-18 用户批准定位 C3 前置的 arxiv 降级；本轮仅一次相同 local-proxy 的静态
arxiv GET，固定既有 probe URL/params，不重试、切出口或重跑整轮前置。
代理通过严格 endpoint 校验及与前轮哈希匹配；`.env` 未改，不执行 durable 安全获取。
执行代码审计身份 `5765079`，生产候选仍为 C2 `d567b26`，项目 .venv Python 3.12.4。

02:15:38.365～02:15:40.286 UTC（北京时间 10:15:38～10:15:40），1922 ms：

- provider GET 准入 **1**，HTTP **200**，probe 可达，单源健康 **1/1**。
- Retry-After 未提供；gate 在本次请求前后均无 unavailable/cooling_down。
- LLM / Tavily 付费 POST / 研究 run 均 **0**，服务未启动，研究额度仍 **44/48**。

源码解释：`probe.ok_for()` 将 HTTP 429 保留为路由可达并发布冷却；
`throttle.observe()` 对部分 5xx 也发布退避；`health_check()` 将 gate 不可用统一投影
为 `rate_limited`。旧前置未记录响应码/headers，不能仅据投影确定限流机制或恢复期限，
也不把本次 200 倒填到旧结果。当前没有复现；无法确认共享出口、上游配额或其他具体原因。
不修改现有节拍/冷却/路由以消除未复现的问题，不与先前另四源拼成全绿。
完整前置、真实 pinned CONNECT/TLS、研究冷启、报告质量与并发仍未在本轮验证；
后续整轮前置及 P01 一次须重新确认具体调用边界。

请求上限指 provider GET 准入层，不含代理可达性 TCP 或隐式 CONNECT 的 wire 请求计数。
控制器固定 GET 和完整静态 URL、发送前 fsync、显式 25 秒总时限；只保存状态码、布尔值、
解析后的 Retry-After 秒数，不保存原 headers/body、URL、代理端点或异常正文。
纯 MockTransport 的 200/429 两项断言通过（真实请求 0），pyflakes 通过，精确临时目录已清理。
仅维护文档进入 Git，生产代码/测试不变，不重复未变更候选的 C2 全套验收。

本地原件 `outputs/o1c-arxiv-diagnosis-20260918/` 保留、不提交。
observation.json SHA256 `d13fa3d8087b891faadf1061b25df08a0f0da9674725a428e67d4a45f22e8cf4`；
admission.json `9411e7a46709ec4d33e4c97d7f7e042f9af1d2ffbdbff0984876ae3f9df1e2d1`。

## 历史：2026-09-17 两项阻断

日期：2026-09-17。仅诊断；产品/测试未修改，研究 run 新增 0，累计 43/48。
工作树起点 `45017ef`，运行代码仍是 O1-B 候选 `51c7c21083da75e8411c1cb062df15a85c3f6322`。
沿用 [O1-C 数据集/分母与停止记录](o1c-single-case-verification.md)，不新增研究质量分母。

## 1. community 健康未通过

本轮执行一次 **community 单源** routed 健康诊断，无 LLM/Tavily/研究调用，也未改通道顺序。
时间 2026-09-17T12:04:53.349252+00:00（北京时间 20:04:53），实际反馈：

- 选中 self-forward；HTTP **400**；API `error_id=502`、`error_name=throttle_violation`。
- `Retry-After` 数字值与 body `backoff` 均未提供；观察到 limited=true、cooling_down=true。
- resolver 输出 `ok=false / status=rate_limited`；没有自动重试或切换出口。

链路：转发 transport 还原 relayed status/body → `throttle.is_limited()` 识别 API 错误编号
→ `observe()` 发布默认冷却（此探测 fallback=5 秒）→ probe 保留可达通道
→ `health_check()` 因 gate 不可用标 degraded。这是**来源拒绝请求，不是断线或 HTTP 502**。
该反馈与 [StackExchange 官方错误定义](https://api.stackexchange.com/docs/error-handling)一致。

可确认的项目缺口：`outbound/probe.py:84` 使用固定社区 params，没有加入
`STACKEXCHANGE_API_KEY`；`retrievers/community.py:17` 的业务请求则会带该 key。
本机该 key 的存在布尔值为 true（未输出值），故健康探测和业务检索凭据资格不一致。
探测还是 `/search/advanced`，业务是 `/search`，不能把一次探测等同全部业务检索资格。

未确认：具体是出口共享 IP、日配额还是方法级限流；上游错误正文未保存，未取得额度及
准确恢复期限，也未用第二出口对比。官方说明无 access_token 请求可能共享 IP 配额，
且存在 IP/方法级限流，所以这些只是候选原因，**不能断言补 key 就会恢复**。
参见 [官方限流规则](https://api.stackexchange.com/docs/throttle)。
进程内队列无法控制转发出口上的其他调用者，重启进程也不能重置上游限制。

原 O1-C 11:50 UTC 的检查仍缺原 status/body；本轮新反馈不能倒填原检查的确切触发原因。
当前不是“重新五源全绿”：另外四源本轮未重测，本地 Chroma 未测，单例仍 not_run。

## 2. 离线时间断言失败

既往首次 53 passed / 1 failed，单项复查通过，均保留。本轮加观察器、不改测试/断言的
同两文件回归为 **54 passed（27.35 秒）**；观察器增加开销，不能用这次通过抹掉前次失败。

已确认的测试设计问题：

- `tests/test_retrieval_throttle.py:441` 的 scale=0.001 把真实秒级间隔缩成
  official 0.5 ms、community 1 ms、arxiv 3 ms、github 6 ms、Tavily 12 ms。
- 本机 Python 3.12.4 `time.monotonic()` 基于 GetTickCount64，报告分辨率 **15.625 ms**；
  80 ms 有界采样也观察到约 15–16 ms 台阶。上述要求全低于该分辨率。
- `throttle.py:92` 在获准时记 next_start；测试在随后进入模拟 client.get/post 时打点
  （第 467 行等），第 498 行却按物理调用时间差断言。这两个起点存在调度/打点延迟。

使用**原 RequestGate**、虚拟时钟、不改实现的确定性反例：间隔设 3 ms；
首次准入 0 ms，在准入后/调用前注入一个时钟台阶延迟；首次调用 15.625 ms；
第二次准入和调用也为 15.625 ms。准入差 15.625 ms 达标，调用时间差却为 0，
精确触发同类断言。反例没有真实请求、等待或知识库/model 操作。

因此不能把该断言失败直接判为“六源结果丢失”或“队列准入间隔未执行”；
首次失败在前面的六源一致性检查之后。反例也揭示**准入节拍不等于任意调度延迟下严格的
物理发包间隔保证**，不能只放宽容差然后宣称供应商限流已解决。
原失败没有具体 source/起点时间线，本轮自然运行未复现，故其具体失败 pair 仍 unknown；
已定位的是可复现的测量/契约错位，不声称百分之百重建首次事件或已修复。

## 3. 建议下一项最小修复（尚未实施）

1. 社区 probe 与业务统一可选 key；保留安全错误分类、限流范围/期限的已知与未知，
   不保存原始正文，不绕路或清空冷却。默认 5 秒不是上游确认的恢复期限。
2. 将时序回归改为确定性调度/虚拟时钟，分别验证准入间隔、并发上限、取消清理、
   backoff 与六源结果一致性；明确物理调用节拍契约，覆盖准入后延迟反例。
   不靠重跑、增大容差或仅把时钟换成高精度来掩盖契约差异。
3. 修复涉及并发/外呼契约时，按项目要求补聚焦测试、全套和独立复审，再考虑明确授权的
   community 重查与 P01 一次准入。单例、批次及 O2 本轮均未执行。

## 原件与校验

原件位于 `outputs/o1c-diagnosis-20260917/`（本地保留、不提交 Git），SHA256：

- community.json：`14a7dc1461828c122c75e4fa5cdc163230ed2b4dff7fda545d0b3a83090d39b7`
- offline.json：`d45cefd4625ee60c2aa6754b16b1a9d5e199af2361c634ae4db0dca0774e25ac`
- clock.json：`3c807f644b5915cb6cf689538ab33e2dc49b9abb23faadb0adb1e343729a7b4a`

仅文档变更，不重复未变更全套；O1-B 1238 全套是历史候选验收，不是本轮新全套结果。
本轮有界反例断言、原件哈希与文档投影、diff 检查通过；无测试临时目录或后台服务。
O1-C/O1 仍未完成，不能把诊断归档当作可靠性或模型语义 gate 通过。
