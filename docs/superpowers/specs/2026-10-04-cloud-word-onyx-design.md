# OrgMesh 云端 Word 与 Onyx 接通设计

2026 年 10 月 4 日 UTC。基线：`74c7d4c85bc77423b440ef63be6618a3315f3927`。供书面设计审阅。

在云端延续现有 Word 架构，完成新建、导入、打开、保存、下载，以及选区 AI 改写、预览、确认和安全恢复。保留 GenOffice 原编辑器和右侧 AI 面板。Onyx 仍是唯一主智能体。Python 保留当前鉴权、租户和版本写入职责。Go 按业务域逐步迁移。

本稿细化已批准的 `2026-10-01-genoffice-word-integration-design.md`，不改变其内容归属、安全限制和验收要求。旧计划中已存在的手工编辑源码必须复用。Mac 后续 AI 实现只有历史报告可读，其源码和补丁尚未取回。本稿不将那些实现或测试计入云端成果。

## 1 当前源码和实际技术栈

| 层 | 当前仓库组件 | 当前作用 |
| --- | --- | --- |
| 平台网页 | TypeScript，Next.js 16.3.3，React 19.2.8，Opal，Tailwind，SWR，next-intl | 平台导航、工具页、同源编辑器外壳、认证和 API 入口 |
| 业务后端与智能体 | Python 3.13，FastAPI 0.133.1，SQLAlchemy 2.0.50，Alembic 1.18.4，LiteLLM 1.93.0 | 权限、租户、会话、工具编排、文档持久化 |
| 数据和文件 | PostgreSQL；现有 PostgreSQL FileStore 模式 | 私有 DOCX 完整字节、不可变版本、会话和事务 |
| 完整搜索与任务 | OpenSearch 3.6.0，Redis 7.4，Celery 5.5.1，Python 模型服务 | 检索、缓存、连接器、索引和后台任务 |
| Word 网页运行时 | GenOffice 固定源码；TypeScript、React、Tiptap 3.31.0、ProseMirror、DOCX 引擎、Vite 7.3.1 | 解析、原编辑区与面板、原保存管线；独立浏览器 bundle |
| 候选执行器 | 计划中的 Node 与 TypeScript 进程；复用上述 schema 和引擎 | 在固定 DOCX 副本中生成和验证候选，不写数据库 |
| 既有 Go 模块 | `services/orgmesh-core`，Go 1.27.1 | Presenton 历史的可选只读投影；没有文档写权或数据库凭证 |

已存在的源码：

- `backend/onyx/server/word_documents.py`：status、列表、新建或导入、元信息、指定版本内容、手工保存。
- `backend/onyx/db/word_documents.py`：owner 约束、不可变版本、行锁、版本比较、幂等结果。
- `backend/onyx/word_documents/{contracts.py,validation.py}`：手工契约、DOCX 校验、确定性空白文档。
- `web/src/sections/workspace/documents/`：列表、编辑器外壳、保存和下载；页面位于 `/app/tools/documents/[id]`。
- `vendor/genoffice/apps/docs/src/renderer/platform/`：宿主接口、手工 HTTP adapter、保存结果不确定时的恢复。
- `vendor/genoffice/apps/docs/src/renderer/browser-main.tsx`：原 App 的网页入口。`AiPanel.tsx` 在网页模式不创建 Electron transport 或本地 AgentLoop。
- `contracts/orgmesh-documents/v1.schema.json` 和 `@orgmesh/docs-runtime/src/contracts.ts`：已有选区、运行、候选和事件类型。

尚未实现的云端产品源码：受限候选执行器，持久 Run/Proposal/Event，Onyx 文档工具与运行绑定，原面板的预览确认恢复。`http-host.ts` 对 start、subscribe、cancel、accept、reject、restore 仍返回 `NOT_ENABLED`。Python VersionResult 和数据库操作约束目前只接受 `import | manual`。声明类型不等于功能实现。

运行状态：Next dev 在 `127.0.0.1:3021` 已就绪。Word 静态 bundle、后台 Python 环境、PostgreSQL、Redis、OpenSearch 和模型服务未就绪。真实浏览器访问此前返回 `ERR_BLOCKED_BY_CLIENT`。该限制仍是验收阻塞。

## 2 路线和一期范围

推荐继续当前 Python 文档域与 Onyx 主循环，补齐 Node 候选执行器和原面板适配。它复用手工保存和权限边界，改动范围最小。

也可先恢复 Mac AI 补丁，但当前无法取得源码。等待会推迟云端目标。另一条路线是先把文档域全部迁 Go，再接 Word；它同时引入新的事务与鉴权边界，本期不采用。

一期 AI 只支持一个普通正文段落内的非空文本选区。它可以保留可证明安全的文字样式，但不修改段落属性或生成换行。模型只输出替换文本，不输出 HTML、代码或文档命令。遇到跨段落、表格、列表、文本框、域、书签、链接、批注或修订等复杂边界，明确提示缩小选区。含其他复杂部分的文档仅在往返保真和未改部分验证通过时允许处理。

用户流程：从工具页新建或导入 DOCX；打开并手工编辑；保存或下载；在原面板对选区提出要求；查看文字差异和只读候选预览；接受或拒绝；接受后重新打开、下载，并可恢复本次 AI 修改前的版本。

一期不增加 Excel、共享编辑、多人合并、全文改写、PDF 导出、供应商设置或第二套智能体。Presenton 保留现有 PPT 职责。`project_id` 在当前 Word API 中仍为 null；一期不新增任意项目或已有共享聊天的绑定。

## 3 组件和运行顺序

原 Docs renderer 经同源 `/office/docs/index.html` 加载。浏览器只通过 `/api/orgmesh/documents` 调用认证 API。frame 保持构建和样式独立，不充当安全边界。身份凭证不跨窗口传递。

Python 文档服务是唯一持久内容写入者。每个 API、状态读取、事件订阅和候选内容请求都检查现有用户及租户会话。每份文档归一个 owner。错误 owner 或租户的标识统一不可见。

Onyx 继续使用现有会话、模型设置、消息持久化及 `handle_stream_message_objects` 到 `run_llm_loop` 的主循环。Word 运行绑定由服务端创建，包含 tenant、owner、document、固定版本、run、chat 和 deadline。Run 绑定 Onyx 已预留的 assistant message ID，不另造聊天消息权威。客户端和模型不能声明这些权限。

Word 专属会话为同一 owner 的持久普通 Onyx 会话，不接受共享、匿名或隐身会话。文档运行最终只能使用 `read_document_selection` 和 `propose_document_rewrite` 两个工具。`allowed_tool_ids` 不能单独充当白名单，因为现有构造器会额外注入 memory 或 search。在服务端专属构造边界禁止额外注入，并在工具执行时重查绑定。一期禁用 multi-model 和 deep-research。普通 chat 的 binding=None 路径保持原行为。

候选执行器复用 CLI 中的 `openDocument`、同版 editor schema 与 `saveDocument`。它从服务端接收固定版本的 DOCX 字节、选区和替换文本。在隔离副本应用文字变换，输出候选完整字节、SHA-256、文字差异和未改部分验证结果。它不接收任意文件路径、URL、用户凭证或数据库权限。

执行器必须有实际进程隔离、禁止外网、只读代码、独立临时目录和资源上限。仅清空环境变量或设置 Node heap 不能证明这些限制。可用受限容器或已获准的 Linux 隔离设施实现。设施未就绪时，受信任 fixture 可做源码测试，但不能开放不受限的用户文档执行。

手工浏览器与真实保存验收先行。通过后完成固定响应的候选与事务，再接现有 Onyx 流。测试模型响应可固定，产品模型入口仍必须调用 Onyx 主循环。真实模型 smoke 需要已批准配置和额度。

## 4 契约和状态

复用现有 v1 的 SelectionRef、RunRef、RunEvent、RunState、ProposalState 和 VersionResult，不另造一套协议。服务端从完整 DOCX 重建同版选区，检查版本哈希、schema、位置、选区文字哈希和内容限制。客户端提交的文字只用于显示。

先保存未保存编辑，成功后冻结 `version_id`、`content_hash`、选区与本地 generation。保存失败或输入法尚在组合时不能启动。任何后续本地编辑使候选失去接受资格；另一标签页保存后，服务端的版本比较也拒绝旧候选。

新增持久 Run、Proposal、Event 和操作幂等记录。现有 Version 追加 `ai_accept | restore`，保留全部旧版本。数据库 enforce 单文档最多一个 queued/running run、单候选只接受一次、幂等请求唯一性，以及必要的同文档关联约束。

运行不因浏览器断流重新生成。投递和领取通过持久状态控制，重复投递不重复开始模型。已开始但模型结果未知的运行，在重启后标为失败；不自动重试产生潜在费用的请求。停止与完成竞争以服务端终态为准，迟到结果不能成为可接受候选。Lite 采用 API 内受控运行器，完整部署可用 Celery 投递同一执行入口；两种适配器都必须通过相同状态和恢复测试。

事件按 sequence 增长，event_id 去重。工具注册 ID、模型调用 ID 和持久 tool_execution_id 各有职责，不能混用。主循环调度工具时建立关联，保留 placement 的轮次、并行位置和 model_index。工具名与到达顺序不能区分并行执行。工具注册须支持现有 Onyx 消息重建。生产代码不依赖仅测试模式出现的 ToolCallDebug。

订阅使用现有 JSON 流语义，不假设原 Onyx 流是 SSE。Onyx 原缓冲默认运行时保留一小时、完成后十分钟；Word 另存本稿规定的持久事件与状态。新增只读状态、候选元信息、候选内容和版本历史查询，用于刷新与结果不确定时的恢复。

每个写请求先鉴权，再查幂等结果，再比较版本。同键同请求返回原结果；同键不同内容冲突。候选对象先写入并校验哈希，事务再锁定文档、验证候选、追加版本、切换 current_version 和记录提交结果。对象或事务失败时不推进版本。

接受成功的返回丢失时，以同一个请求键查原结果，不重复生成或提交。拒绝不产生内容版本。只读预览不替换用户正在编辑的文档。接受后的界面加载失败可重新读取成功版本；切换文档或身份后，旧响应不能覆盖新编辑器。

恢复只支持撤销仍为最新提交的那次 AI 修改。本地须无未保存编辑。它复制该 AI 版本的父版本字节，追加 restore 版本并记录来源，保留历史。已有后续保存时返回 VERSION_CONFLICT；不强制回滚，不调用旧的整份 setContent(snapshot) 回滚入口。

## 5 固定限制和验收要求

沿用已批准的限制：上传及候选不超过 20 MiB；解压不超过 100 MiB 和 10,000 entries；选区不超过 8,000 Unicode code points；事件和未接受候选保留 24 小时有效期；单运行总时限 120 秒。沿旧计划，执行器 RSS 上限 512 MiB，单次执行不超过 30 秒；实测不足时报告并审阅变更，不静默放宽。看门狗实际终止超限子进程；Celery 线程池的 time_limit 不能充当限制证明。

拒绝加密文件、宏、activeX/OLE、altChunk、危险路径、ZIP 炸弹、XML 实体和外部关系。XML 属性按解析后的值校验，覆盖十进制和十六进制字符实体编码的 External。模型文本按文字处理。文档提示注入不得增加工具或选区范围。诊断日志只含 ID、错误码、时间和大小，不含正文或提示词。

Gate A：真实浏览器加载原 App、工具栏和面板，无 Electron；打开、编辑、保存、重开。验证中文输入、emoji、原布局、禁用桌面入口与无外部资源请求。通过受信任 fixture 的原样往返和复杂 parts 保真矩阵。

Gate B：真实认证 API 与 PostgreSQL 完成新建、导入、保存、重开、下载；字节哈希一致。真实行锁、CAS、同键重试、跨 owner 和租户 schema、存储/事务失败均通过。SQLite 和依赖替身只能证明隔离契约，不能证明这些结果。

AI 验收：固定响应通过选区候选、预览、接受、拒绝、刷新、下载、恢复，以及手工编辑、双标签、停止迟到结果、双击接受、响应丢失、事件过期、身份切换、输入法组合和异常退出。再做一次获准的真实模型 smoke。缺真实模型时明确标为未验。

浏览器 `ERR_BLOCKED_BY_CLIENT` 仍需平台允许的真实访问路径解决。不得改 hostname、端口、浏览器、代理或关闭限制规避。源码、构建、Node、JSDOM、静态截图均不替代浏览器验收。Gate A 未通过时只准备后续测试和文档，不实现后台 AI 产品路径。

## 6 云端依赖和资源

已安装：Node 24.19.0、npm 11.9.0、Python 3.13.5、uv，以及已恢复的 web 依赖与 Bun。Node 满足 GenOffice `>=22.12.0`，npm 满足 `>=10`。无需为 Word 安装 Rust sidecar 或 Electron 桌面二进制。

需要恢复：GenOffice 锁文件的 npm 依赖；使用 `npm ci --ignore-scripts --no-audit --no-fund`，不运行 postinstall 的 Electron 安装。Python 按仓库 uv.lock 的 backend 组安装；不默认同步 model_server 和全部 dev/ee 组。实际 API 启动缺项必须逐项记录，不能靠伪模块运行产品服务。当前标准后端测试先在 fastapi_users 缺失处停止。

最小手工与单租户 chat 栈：web + Python API + 独立 PostgreSQL，FILE_STORE_BACKEND、CACHE_BACKEND、AUTH_BACKEND 均为 postgres，DISABLE_VECTOR_DB=true，ENABLE_CRAFT=false。这不启用连接器或 RAG。加入 AI 后还需受限 Node 候选执行器。现有代码拒绝 DISABLE_VECTOR_DB 与 MULTI_TENANT 组合，因此 Lite 不能证明真实多租户登录或检索。

完整栈另需 Redis、OpenSearch、共享 CPU 模型服务和 Celery；Presenton 是独立可选服务。PostgreSQL FileStore 模式不要求 MinIO。完整检索不应在当前云主机与中文视频任务并行加载。

当前没有 PostgreSQL 或 Docker/Podman。基础数据库可使用官方 PostgreSQL 或 Debian 官方软件源；容器路线使用官方 Docker Engine 与 Compose。若安装涉及 daemon、网络、uidmap、权限或内核设置，先提交具体动作供批准。不得直接沿用 compose 的旧 Mac 静态网段；不得连接真实生产库。

仓库镜像基线是 PostgreSQL 15.2-alpine、Redis 7.4-alpine、OpenSearch 3.6.0、自建源码后端基底 onyx-backend:v4.8.1。执行前核对当前官方发布和测试兼容性；此处记录源码基线，不把旧镜像标签当作安全推荐。

资源预算区分配置上限和实测值：

- 现有 API 1.5 GiB + web 0.5 GiB + PostgreSQL 0.5 GiB，合计 2.5 GiB 的配置上限，不是最小内存保证。候选执行器再预留 0.5 GiB。
- 完整搜索再加 Redis 0.25、OpenSearch 1.5、模型 2、background 4 GiB，合计 10.25 GiB；加 Presenton 3 GiB 为 13.25 GiB，均不含额外系统和构建开销。
- 当前主机总内存约 9.7 GiB，无 swap；11:44 UTC 可用约 7.2 GiB。中文 TTS 峰值约 3 GiB。大构建、模型加载和后台全组安装必须串行协调，保留至少 2 GiB 可用内存。
- 当前 workspace 可用约 14 GiB；保留至少 1 GiB。依赖和镜像下载体积尚未实测。先检查缓存，再分批安装，不承诺全部栈同时常驻。

缺少模型供应商配置/凭据和已批准调用额度。缺少真实 Feishu 凭据，但它不是 Word 一期的前置条件。新凭据、持久测试账号、付费调用或生产迁移不随本稿自动批准；测试只使用获准的隔离库和测试身份，不记录或上传秘密。

验收环境关闭 Next 和 Onyx 可选遥测，清空 Sentry DSN/token，禁止源码上传与 release 写入，不新增 PostHog 凭据。已修配置只证明构建插件的行为，不代表配置了 DSN 的运行时不会上报。完整 Next build 尚无成功终态或产物；此前会话读取被取消，原因未确定。未经明确可重试依据，不重复该被拒读取或重启大构建。

官方安装参考：Docker Debian 安装 https://docs.docker.com/engine/install/debian/ ，Docker rootless https://docs.docker.com/engine/security/rootless/ ，OpenSearch Docker https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/ ，PostgreSQL 官方镜像 https://hub.docker.com/_/postgres 。

## 7 实施顺序与 Go 方向

实施计划以现有路径为基线，避免旧计划的未建目录假设。顺序为：恢复浏览器依赖与 bundle 并完成 Gate A；复核现有手工 API 与迁移并完成 Gate B；生成可验证的窄选区候选；追加候选与恢复事务；接 Onyx 运行和持久事件；接原面板；完成故障、隔离、兼容性和全链路验收。

新增迁移接在当前唯一的 People head `d83f0b6c1e92` 后。2026-10-05 发布复核确认：main 基线 head 为 `c71e9a2d4f60`，恢复后 head 为 `d83f0b6c1e92`；`c7bf5721733e` 有后继 `f1ca58b2f2ec`，是该链祖先，并非另一个 head。执行前仍核对目标数据库的实际 revision 和源码图；只在明确的隔离数据库按已审阅迁移图执行，不修改生产 revision 或自动合并分支。

Go 延续 read-only history 投影。Word API、事件及版本契约保持语言无关。后续迁移可按文档元信息、查询投影、写入域分期替换。每阶段只有一个写入者；先有契约测试与真实 PostgreSQL 事务证据，再切写权。本期不把 Python Onyx agent 或 DOCX 引擎重写成 Go。

本稿审阅通过后，定稿逐任务实施计划并确认执行方式。计划列出每项文件、接口、RED→GREEN 测试、验证命令和独立审查。此前只进行源码检查与文档准备；不写产品代码、安装新产品依赖、运行模型、推送或部署。

## 8 核查依据

- `web/package.json`、根 `pyproject.toml`、`vendor/genoffice/{package.json,UPSTREAM.json}`、`vendor/genoffice/apps/docs/package.json`、`services/orgmesh-core/go.mod`：组件与版本。
- `backend/onyx/server/word_documents.py`、`backend/onyx/db/word_documents.py`、`backend/onyx/db/models.py`、`backend/onyx/word_documents/`：已实现的手工 API 与操作约束。
- `vendor/genoffice/apps/docs/src/renderer/{browser-main.tsx,platform/host.ts,platform/http-host.ts,ai/AiPanel.tsx}`：同源宿主、原 UI 与尚未接通的 AI 方法。
- `vendor/genoffice/packages/cli/src/formats/docx.ts:189` 和 `:211`：已有 Node 打开与完整保存的复用入口。
- `backend/onyx/chat/process_message.py`、`backend/onyx/tools/tool_constructor.py`、`backend/onyx/server/query_and_chat/chat_backend.py`：Onyx 主循环、工具构造和会话权限。
- `backend/onyx/main.py:309`：PostgreSQL cache 与 no-vector 模式限制；`:323`：Lite 与 MULTI_TENANT/Craft 不兼容。
- `deployment/docker_compose/docker-compose.{onyx-lite,orgmesh,orgmesh-full,orgmesh-presenton}.yml` 与 `deployment/Dockerfile.orgmesh-backend`：服务职责、配置上限和镜像基线。
- `docs/word-manual-flow.md`：后续手工实现事实；`docs/genoffice-word-acceptance-matrix.md` 是更早的浏览器 checkpoint，不用于判断当前手工 API 是否存在。
- `docs/superpowers/specs/2026-10-01-genoffice-word-integration-design.md` 与同日 plan：既有设计、限制、Gate A/B 和执行顺序。
