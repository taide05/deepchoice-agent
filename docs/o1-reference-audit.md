# 2026-09-16 O1 历史参考核验记录

核验日期：2026-09-16。案例版本：`product-baseline-v1 / 0.1.1-candidate`。
核验者：助手，使用官方文档逐项核对；当时提案等待冻结，现不构成待审批任务。不是人工盲评分数，也不预设最终赢家。

以下表格保留当时的参考和评分说明，不作为所有新题的通用要求，也未在本次联网复核。
开发可按需要复用；若作为新评测依据，核对实际适用版本并注明数据暴露情况。

| Case | 版本/参考依据 | 核验边界与可接受结论 |
|---|---|---|
| P01 | [SQLite 用途](https://www.sqlite.org/whentouse.html)，滚动；[PostgreSQL 18 并发](https://www.postgresql.org/docs/18/mvcc.html) | SQLite 同一时刻单写者；日活不能代替写并发。优先简化或条件性选择 PostgreSQL 均可，必须说明写竞争、备份与迁移条件。不能编造强一致需求；SQLite 本身支持事务。 |
| P02 | [pgvector 0.8.6](https://github.com/pgvector/pgvector/tree/v0.8.6)；[Qdrant 过滤](https://qdrant.tech/documentation/search/filtering/)，滚动 | pgvector 近似索引的过滤/扫描边界需核对；Qdrant 支持 payload 条件过滤。现有数据库与新增运维面都计入，100 万条不是一方必胜的性能证据；过滤功能不自动提供租户权限。 |
| P03 | [Django 6.0 admin](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/) 与 [async](https://docs.djangoproject.com/en/6.0/topics/async/)；[FastAPI 特性](https://fastapi.tiangolo.com/features/)，滚动 | Django 有内置内部管理界面及有条件的异步支持。FastAPI 的 API 能力不等于完整业务后台；第三方组件和团队成本必须说清。Django 倾向可接受，但明确反转条件的 FastAPI 方案也可。 |
| P04 | [FastAPI 后台任务](https://fastapi.tiangolo.com/tutorial/background-tasks/)，滚动；[Celery 5.6 tasks](https://docs.celeryq.dev/en/v5.6.3/userguide/tasks.html)，页面标题显示 5.6.2 | 进程内任务不提供重启持久恢复。Celery ack/redelivery 依赖设置与故障条件，不能说天然 exactly-once 或所有故障下必然重投。持久队列或有可靠收尾的阶段性持久任务方案均可；业务幂等必答。 |
| P05 | [HTTPX HTTP/2](https://www.python-httpx.org/http2/)，滚动；[aiohttp 3.14.3 client](https://docs.aiohttp.org/en/stable/client_advanced.html) | HTTPX 的 Client/AsyncClient 可启用 HTTP/2，需可选依赖及显式开关；aiohttp 的异步会话/连接池能力有依据。未核验到的 aiohttp HTTP/2 能力记未知，不从“官方页面未提到”推断绝对不支持。中文关键声明需与英文原始段落对应。 |
| P06 | [Bun HTTP server](https://bun.com/docs/runtime/http/server)，滚动；[Node.js 26.8.2 API](https://nodejs.org/docs/latest/api/) | 两者存在 HTTP/runtime API，但这些页面不提供本团队数据库 I/O 服务的配对性能证明。不预设已经核实相反 benchmark；固定倍数收益须有版本/硬件/负载证据。基于经验保留 Node 或验证后采用 Bun 均可。 |
| P07 | [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)；[Poetry basic usage](https://python-poetry.org/docs/basic-usage/)，均滚动 | 两者有各自锁文件与项目流程，不能当成直接互换。公开文档充分不等于本项目已有迁移收益证据；分支试点、CI/发布/锁文件核验和回滚必答，不要求无条件迁移。 |
| P08 | [Redis 类型](https://redis.io/docs/latest/develop/data-types/)；[Memcached 文档](https://docs.memcached.org/)，均滚动 | Redis 有多类结构；Memcached 可作内存对象缓存。不要把“不需要持久化”直接推出唯一赢家，也不要绝对宣称 Memcached 没有任何重启/恢复选项。列未知条件；唯一 evidence-insufficient gate 未触发也可给合格条件性报告。 |
| P09 | [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)；[Temporal workflow](https://docs.temporal.io/workflow-execution)，均滚动 | 持久 checkpointer 和事件历史/replay 不是相同恢复模型，内存 checkpointer 不提供跨进程恢复。外部副作用仍有业务责任，不能将任一框架描述为任意 API 天然 exactly-once。条件性推荐均可。 |
| P10 | [GraphQL performance](https://graphql.org/learn/performance/)；[RFC 9110](https://datatracker.ietf.org/doc/html/rfc9110)，2022-06 | GraphQL 有 N+1 风险，可通过批量/缓存缓解；GET 查询也可利用 HTTP 缓存，不能说 GraphQL 一律不可缓存。请求数不是端到端延迟的充分证明。REST 聚合优化或 GraphQL 局部试点均可。 |
| P11 | [Kafka 4.2](https://kafka.apache.org/42/getting-started/introduction/)；[RabbitMQ 4.3 Streams](https://www.rabbitmq.com/docs/streams) | Kafka 保留日志可重读，顺序有分区边界；**RabbitMQ Streams 同样有持久非破坏消费和重放能力**，不能把 RabbitMQ 等同经典破坏式队列，也不能因此强制 Kafka。说明实际队列类型、重试/死信、运维与交付边界。 |
| P12 | [AWS Lambda best practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)；[Kubernetes Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)，均滚动 | Lambda 需要治理连接复用/闲置连接、并发和延迟；Deployment 是声明式副本/滚动更新管理，不等于所有云容器服务的 SLA 或价格。厂商示例不能外推为所有云的确定账单；测量冷启动、连接、峰值和 P95 后条件性决定。 |

## 现在如何使用

本页不再要求按原 12 题、8/4 分组、HITL、双评及 1.0.0 冻结流程执行。
需要其中的参考时按题取用；旧评分规则仅解释对应历史结果。参考答案可用于开发，
使用后标明开发暴露，不继续宣称这些题对该版本未见。没有新的付费授权由本页产生。
