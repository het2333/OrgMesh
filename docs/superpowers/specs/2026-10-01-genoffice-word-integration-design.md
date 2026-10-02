# OrgMesh 原生 Word 编辑集成设计

2026 年 10 月 1 日  |  版本 1  |  供设计评审

保留 GenOffice Docs 原编辑器和右侧 AI 面板，由 Onyx 主智能体负责理解指令与工具编排。OrgMesh 负责身份、文件归属、候选修改、版本提交和历史。第一期完成选区改写闭环，并为后续 Excel 接入保留清晰边界。

## 1 目标与范围

成功标准：打开自己拥有的 Word 文档，选中文字，在原右侧面板要求改写；查看差异，接受或拒绝；接受后形成可重新打开的版本，并可安全撤销。生成期间发生手动编辑或其他标签页保存时，旧建议不能覆盖新内容。

- 一期支持浏览器中的 DOCX 打开、正文编辑、保存与下载，以及连续正文段落内的文本选区改写。使用 GenOffice 原解析、编辑和保存能力，不从纯文本重建整份 Word。

- AI 改写只改变选区内的文字与必要段落换行。保留原有格式继承规则；不让模型生成任意 HTML、代码或低层文档命令。

- 一期不支持跨表格、文本框、域、批注或修订边界的 AI 选区修改；遇到这类选区明确提示缩小选区。未通过保真验证的文档拒绝编辑，不静默降级。

- 本期不包含 Excel、PPT、多人实时合并、共享编辑、离线同步、模型供应商设置、PDF 导出或替换 Onyx 主智能体。Presenton 继续承担现有幻灯片功能。

## 2 源码事实与路线选择

GenOffice Docs 的 Tiptap 编辑器已有外部命令桥接，复用本地工具并串行执行。右侧面板直接创建 AgentLoop；Electron transport 只负责模型通信。换模型地址不能让 Onyx 接管编排。[S1–S3]

原界面依赖 window.desktop 等 Electron IPC。renderer 的 Vite 配置用于 Electron 开发加载，不证明浏览器可独立运行。private:true 是本地 workspace 未发布标记，当前没有已核实的私有依赖缺失结论。[S3、S4、S9]

选择浏览器适配路线：复用原 UI、文档模型与工具语义，隔离宿主接口。仅接后台 CLI/MCP 无法满足原面板目标；保留独立 Electron 客户端则无法完成浏览器内融合。

## 3 组件与责任

### 原编辑器与浏览器宿主接口

将 Docs renderer 作为独立、可版本锁定的前端模块，经 OrgMesh 同源 /office/docs 路由加载。使用同源 frame 保持样式与构建独立；frame 不是安全边界。它使用同源认证 API，不跨窗口传递身份令牌。保留原编辑区、工具栏、选区提示与右侧 AI 面板。

新增 DocsHostPort，承担打开与保存文档、附件选择、下载、偏好、会话和运行订阅。实现 BrowserHostAdapter，把必要的 window.desktop 与 projectApi 调用替换为受限接口。文件选择改用浏览器上传；不模拟文件系统路径、任意 IPC 或全部桌面 API。未支持的桌面功能隐藏并禁用。

### OrgMesh 文档服务

首期在现有 Python 认证与租户边界内提供文档 API，并成为唯一文档写入者。负责 owner 校验、项目与会话关联、版本比较、幂等提交及历史查询。它不调用模型，也不承担 Word 格式转换。公开接口保持语言无关，后续可整体迁移到 Go，避免两套服务同时写同一实体。

### Onyx 主智能体与确定性文档执行器

右侧面板以 Onyx 会话为唯一聊天记录来源，用运行适配器替换本地 AgentLoop。Onyx 工具只允许读取本次固定版本的上下文和创建选区改写候选。工具返回 proposal_id 后，Onyx 可结束本轮；等待用户接受不占用模型循环。

独立 Node 文档执行器复用 GenOffice Docs 的解析、选区变换和保存实现，在隔离副本上生成候选 DOCX。CLI 已有 Node 下打开、修改、保存的代码路径，可作为复用依据；浏览器与执行器须锁定同一编辑 schema 与引擎版本。[S5]

执行器没有数据库写权、用户凭证、任意路径读写或外网访问。它接收已授权版本字节与固定选区，输出候选文件、结构化差异和验证结果。任意源代码、插件、宏和外部链接执行均不在工具能力内。

## 4 文件与历史归属

新增独立文档域，不复用 Presenton 的 PPT 专用表。Document 保存 tenant、owner、标题、project_id、current_version_id；Version 保存不可变 DOCX 对象、哈希、parent_version_id、操作类型及创建者。Run 与 Proposal 关联 document、base_version、Onyx chat/message、候选版本及状态。

DOCX 完整字节是持久版本的权威内容；ProseMirror JSON、选区与解析结果只是绑定版本和引擎版本的缓存，不能单独充当完整 Word 备份。既有图片、样式、页眉页脚等必须通过原保存管线保留。[S6]

关联项目、会话时检查同一 owner 和租户；读取链接时重新检查访问权。首期只接受自有普通文档与会话，不导入共享或隐身来源。现有 Go readmodel 仍只投影已授权的 Presenton 历史页，不取得新文档写权。

## 5 一次选区改写的完整流程

- 打开：服务端鉴权后返回当前版本及文档内容。浏览器载入完整文档再允许发起 AI，不能在分段加载尚未完成时截取上下文。

- 固定：先保存未保存编辑；服务端以 expected_version 做比较并返回新版本。保存失败则不启动 AI。随后冻结 version_id、content_hash、schema_version、选区位置、原文摘要哈希和 local_generation。

- 请求：发送指令和 selection_ref 给文档服务。服务端从版本内容验证选区，创建 run_id；只向 Onyx 提供选区、必要相邻文本与文档结构摘要。客户端提供的文字不是权限或内容依据。

- 生成：Onyx 请求受限工具，输出 replacement_text。执行器在固定版本副本上应用修改，生成候选字节并重新解析；检查选区外内容及文档附属部分没有非预期改变。失败则不给用户可接受的候选。

- 预览：原面板显示文本差异与候选状态，编辑区可切换只读候选预览。原文档仍是当前版本。拒绝只改变候选状态；不产生内容版本。

- 接受：提交 proposal_id、expected_version 和幂等键。服务端在事务中锁定当前文档并比较版本；校验 owner、候选状态、候选完整性和有效期。成功后追加版本、更新 current_version、标记候选已接受并记录历史。

- 确认：浏览器收到已提交版本后才刷新编辑器与历史。刷新失败可重新读取已提交版本，不能再次启动生成。导出的文件必须与该版本内容哈希一致。

## 6 并发与安全撤销

任何手动编辑都会增加本地 generation。只要它不同于发起 AI 时的值，旧候选立即失去“接受”资格，即使用户尚未保存。重新保存后可发起新一轮；一期不自动重定位选区、不重放旧建议、不自动合并。

另一标签页或会话提交后，服务端 current_version 改变。旧保存、接受或撤销请求返回 VERSION_CONFLICT，并返回用户有权看到的当前版本标识。界面保留本地内容供复制或下载，不自动覆盖，也不盲目重试写入。

“撤销这次 AI 修改”仅在该修改仍是当前最新版本、且本地没有未保存编辑时可直接执行。撤销复制父版本内容并追加一个 restore 版本，同时记录 restored_from；它不删除历史。若后来已有编辑，显示冲突并保留版本查看能力，首期不提供跨版本强制回滚。

原生键盘撤销继续作为本地编辑操作，下一次保存仍受版本比较约束。原 AI 面板整份 setContent(snapshot) 回滚入口必须改接上述版本接口，避免抹掉后续编辑。[S2]

## 7 API 与运行事件契约

所有新路由位于 /orgmesh/documents；浏览器沿用现有 /api 入口。建议资源：创建与读取文档、POST /{id}/versions 保存、POST /{id}/runs 发起、GET /runs/{run_id}/events 订阅、POST /runs/{run_id}/cancel 停止、POST /proposals/{id}/accept 或 /reject，以及 POST /{id}/restore。

每次写入携带客户端生成的幂等键。作用域为 tenant、owner、操作与文档；先查幂等结果，再做版本比较；同键同请求返回原结果，同键不同负载返回冲突。状态未知时通过 run_id、proposal_id 或幂等键查结果，禁止重放模型请求来修复保存失败。

事件使用 schema_version、run_id、sequence、event_id 和 type；工具事件额外带 tool_execution_id，候选事件带 proposal_id。最小类型为 message_delta、tool_started、tool_finished、proposal_ready、run_completed、run_cancelled、run_failed。客户端按 event_id 去重，按 sequence 续传。

适配器解析 Onyx 现有流并保留 placement 的轮次及并行位置。生产环境不能依赖 ToolCallDebug：其 tool_call_id 只在集成测试模式发出。稳定工具标识来自文档工具执行记录，而非工具名或 UI 到达顺序。[S7]

Run 状态为 queued、running、completed、cancelled、failed；Proposal 状态为 ready、accepted、rejected、stale、expired。completed 表示生成结束，不表示用户接受。停止与完成竞争时，以文档服务终态为准；迟到结果不得变成可接受候选。

事件日志保留 24 小时，候选默认 24 小时后过期；已接受版本不随事件到期删除。游标失效时返回明确状态，客户端读取持久 run/proposal 状态恢复，不重新运行模型。单份文档最多一个运行中的 AI 请求。

## 8 事务 失败与访问控制

先写不可变候选对象并核对哈希，再在数据库事务中引用它并切换当前版本；数据库不得指向未完成对象。事务失败可能留下未引用对象，由受控清理回收。提交成功但响应丢失时，通过幂等结果恢复，不生成第二个版本。

每次打开、保存、订阅、预览、接受、拒绝和下载都重新检查 tenant 与 owner。正文和预览必须清理可执行内容并受 CSP 约束。模型输出和文档内指令均是不可信数据，不能扩大工具范围。Onyx 只收到服务端绑定的文档上下文，不获得可用于其他文件的任意标识。

上传初始上限为 20 MiB，解压上限为 100 MiB 与 10000 个 ZIP 条目；选区最长 8000 个字符。禁止加密 DOCX、宏、外部资源自动获取和危险路径。执行器有硬超时、内存与输出大小限制；初始运行总时限为 120 秒。超限明确失败，不自动降级为全文件改写。

诊断日志只记运行 ID、固定错误码、耗时与字节计数，不记正文或提示词。聊天与事件中的消息内容作为私有用户数据保存；正文与候选沿用私有对象存储、现行备份和删除策略。首期不提供文档硬删除 API；删除能力另行设计与授权。

## 9 验收与后续审批

先通过浏览器移植与 DOCX 往返保存验证，才能实现 AI 修改闭环。不得以 Node 解析成功代替浏览器 UI、真实保存或 Word 保真验证。测试优先用固定工具响应，减少真实模型调用成本。

- 浏览器：不依赖 Electron preload 即可打开、编辑、保存、重新载入与下载；原面板布局和选区高亮正常；不支持的桌面入口不可触发。

- 保真：覆盖中英文、样式、编号、表格、图片、页眉页脚、批注和修订样本。合法正文选区改写后，选区外语义与附属资源不变；XML 序列化差异不直接视为内容变化。无法证明保真的样本禁止提交。

- 闭环：生成、预览、接受、拒绝、保存、刷新、重新打开、下载及安全撤销全部经过真实浏览器与 API；每次接受只产生一个版本。

- 竞争：生成期间手动输入、切换文件、停止后迟到结果、双击接受、两标签页同时保存、响应丢失后重试、接受后再编辑再撤销，都不得丢失新内容。

- 隔离：跨用户与跨租户读取、篡改文档或版本 ID、直接访问候选字节、订阅他人事件、恶意 DOCX、ZIP 炸弹及文档提示注入必须被拒绝。

- 故障：执行器退出、模型超时、候选验证失败、对象写入失败、事务失败、事件过期和身份失效都能恢复到明确状态，不重复生成或提交。

本稿批准后才进入实施计划评审；计划需列出隔离环境、受影响模块、验证顺序与执行方式。Go 主干迁移、Presenton 既有补丁、Excel 扩展和部署均不随本稿批准自动执行。

## 10 代码依据

GenOffice 固定版本为 676bf4d51239874d82d0d3edd10682c15ada367f。OrgMesh 核查基线为 ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e；既有 Presenton 历史与 Go 只读投影补丁仍未提交，保持其现有职责。下列是事实依据；API、状态机和限额是本设计的待评审决定。

- [S1  外部命令进入原编辑器并串行执行](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/apps/docs/src/renderer/mcp-bridge.ts#L8-L18)
- [S2  原面板 AgentLoop 快照与回滚](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/apps/docs/src/renderer/ai/AiPanel.tsx)
- [S3  Electron 模型流 transport](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/apps/docs/src/renderer/ai/transport.ts)
- [S4  Renderer 开发配置](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/apps/docs/vite.renderer.config.ts)
- [S5  Node 文档打开与完整保存](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/packages/cli/src/formats/docx.ts#L189-L234)
- [S6  原文档生命周期与 DOCX 保存管线](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/apps/docs/src/renderer/file-actions.ts#L689-L803)
- [S7  Onyx 流模型与工具调试事件](https://github.com/het2333/OrgMesh/blob/ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e/backend/onyx/chat/llm_loop.py#L1217-L1228)
- [S8  Onyx 运行流与恢复入口](https://github.com/het2333/OrgMesh/blob/ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e/backend/onyx/server/query_and_chat/chat_backend.py#L1291-L1368)
- [S9  本地 workspace 与未发布标记](https://github.com/genspark-ai/genoffice/blob/676bf4d51239874d82d0d3edd10682c15ada367f/package.json)
