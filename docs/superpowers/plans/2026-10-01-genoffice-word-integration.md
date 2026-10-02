# GenOffice Word Integration Implementation Plan

> 执行说明：按用户选择的执行方式逐项完成。每项先写失败测试，再实现最小代码，再复核与局部提交。下列复选框用于执行时记录，本文件本身不表示已经执行。

**Goal:** 在 OrgMesh 浏览器内保留 GenOffice Docs 原编辑器和右侧面板，完成 Onyx 驱动的选区改写、预览、确认、版本历史与安全撤销。

**Architecture:** Python 文档服务是唯一内容写入者。Onyx 保留主编排；隔离 Node 执行器仅处理固定版本副本。原 Docs renderer 通过 BrowserHostAdapter 接平台接口，原 AgentLoop 不在网页模式运行。

**Tech Stack:** 现有 Python 3.13、FastAPI、SQLAlchemy、PostgreSQL、Celery、Next.js、React；GenOffice 固定版本中的 Tiptap、TypeScript、Vite 与文档引擎。不引入另一套智能体框架。

**Spec:** `docs/superpowers/specs/2026-10-01-genoffice-word-integration-design.md`，用户于 2026-10-01 10:52 UTC 批准的版本 1。

## Global Constraints

- GenOffice 固定为 `676bf4d51239874d82d0d3edd10682c15ada367f`；OrgMesh 源码核查基线为 `ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e`。
- 原编辑器、工具栏、选区提示和右侧面板保留；浏览器宿主不模拟任意文件路径或整个 Electron API。
- “一期不支持跨表格、文本框、域、批注或修订边界的 AI 选区修改”；候选输出只允许文字与必要段落换行。
- “上传初始上限为 20 MiB，解压上限为 100 MiB 与 10000 个 ZIP 条目；选区最长 8000 个字符。” 字符数采用 Unicode code point，位置采用编辑器 schema 的位置单位，两者不可混用。
- “事件日志保留 24 小时，候选默认 24 小时后过期”；“单份文档最多一个运行中的 AI 请求”；“初始运行总时限为 120 秒”。
- 任何写入先鉴权，再查幂等结果，再比较当前版本。同键同内容返回原结果；同键不同内容冲突。禁止自动覆盖、自动合并或通过重跑模型修复结果未知。
- DOCX 完整字节是版本权威内容；Node 执行器不能访问数据库、用户凭证或外网。既有 Go readmodel 与 Presenton 路径不变。
- 只支持同一租户 owner 的普通文档、项目与会话。源文档、候选、事件、聊天均是私有用户数据；诊断日志不含正文和提示词。
- 新增功能默认关闭。无推送、部署、生产迁移、持续权限扩展、Excel 接入或替换 Onyx；遇到新的权限或非官方依赖要求先停下报告。
- 新文案沿用各自 i18n 系统；OrgMesh 文案同步九个 locale。DB 查询全部位于 `backend/onyx/db/`；API 返回使用函数注解。

## Review Focus

1. 中文输入法正在组合、emoji 代理对和组合字符：不能冻结半个字符或截断用户尚未提交的输入。任务 2 与 6 测试。
2. 候选生成或接受后马上切换文档：旧文档的响应不能改变新文档，也不能丢掉旧文档的成功结果。任务 6 测试。
3. 浏览器后退恢复页面、退出并更换用户：不能沿用上一用户的文档缓存、事件流或候选。任务 4 与 6 测试。
4. DOCX 含嵌入字体、altChunk 或外部图片关系：不能触发字体权限、外网请求或可执行内容；不能静默丢掉未改部分。任务 1、2 与 8 测试。
5. 接受已提交但返回丢失，再遇事件 TTL 到期：应能查持久结果，不能产生第二版本或重复模型费用。任务 3、5 与 8 测试。

## 工作区与文件结构

执行开始时建立隔离工作树。不得在已有 50 文件暂存补丁的工作树直接实施，不得 `git add .`。首期从核查基线建立独立分支，复制已批准的 spec 与 plan；本功能不依赖未提交的 Presenton/Go 补丁。最终在另一个临时树检验与已审定补丁的兼容性，原树不变。

下列新目录只在实施获批后创建。`vendor/genoffice/` 是保留 LICENSE、NOTICE、原 lockfile 和来源记录的固定上游副本，不引用可漂移的 main。它不是当前已存在的 checkout。

- `vendor/genoffice/apps/docs/`：原 Docs UI、浏览器入口、host port 与原面板运行适配。
- `vendor/genoffice/packages/orgmesh-docs-runtime/`（package name 为 `@orgmesh/docs-runtime`）：只处理固定 DOCX 副本的 workspace 包，复用上游 schema 与保存实现。
- `contracts/orgmesh-documents/v1.schema.json`：跨 Python 与 TS 的 wire contract，不包含业务权限决定。
- `backend/onyx/documents/`：契约、存储适配、执行器客户端、文档命令与恢复；`backend/onyx/db/documents.py` 独占 SQL。
- `backend/onyx/documents/onyx_runtime.py` 与专属工具：Onyx 运行绑定和事件转换，不重写通用聊天循环。
- `web/src/sections/workspace/documents/`：平台文档列表、历史、编辑器外壳；内嵌保留的原 Docs UI。
- `backend/tests/unit/orgmesh/documents/`、`backend/tests/integration/tests/orgmesh_documents/`、`web/tests/e2e/orgmesh-documents/`：分层验收。

## 共享接口决定

这些类型由任务 1 固定 schema 与 TS 契约，任务 2 增加 Pydantic 定义与跨语言校验；不得让模型或客户端指定 tenant、owner、对象路径或可访问文件集合。

- `SelectionRef = {version_id, content_hash, schema_version, from, to, selected_text_hash}`；所有 ID 为 UUID 字符串，哈希为 SHA-256 hex；`from/to` 来自固定版本的同版编辑器，`from < to`。
- `DocumentSnapshot = {document_id, version_id, content_hash, title, project_id}`；`VersionResult` 再加 `parent_version_id` 与操作类型 `import | manual | ai_accept | restore`。内容通过已鉴权的二进制路由读取。
- `CandidateInput = {run_id, selection_ref, replacement_text}`；`CandidateResult = {candidate_hash, diff, unchanged_parts_ok}`，候选字节与 JSON 分开传输。`diff` 为有序 `{kind: equal | insert | delete, text}` 列表。
- `RunEvent = {schema_version: 1, run_id, sequence, event_id, type, payload}`；顺序从 1 开始。事件类型与 Run/Proposal 状态直接复用 spec 第 7 节，工具 payload 含 `tool_execution_id`。
- `DocRunBinding = {tenant_id, owner_id, document_id, base_version_id, run_id, chat_session_id, deadline_at}`，仅由服务端构造，不进入公开 SendMessageRequest。
- `DocsHostPort` 公开 `openDocument(id): Promise<DocumentSnapshot>`、`readVersion(id, versionId): Promise<ArrayBuffer>`、`saveVersion(id, expectedVersion, bytes, idempotencyKey): Promise<VersionResult>`、`startRun(id, selection, instruction, idempotencyKey): Promise<RunRef>`、`subscribeRun(runId, cursor, signal): AsyncIterable<RunEvent>`、`cancelRun(runId, key): Promise<RunState>`、`acceptProposal(id, expectedVersion, key): Promise<VersionResult>`、`rejectProposal(id, key): Promise<ProposalState>`、`restoreVersion(id, expectedVersion, key): Promise<VersionResult>`。`RunRef` 含 run_id、chat_session_id；其状态类型使用上述 schema。

## Task 1 证明原编辑器能够在浏览器中运行

**Files**
- Create: `contracts/orgmesh-documents/v1.schema.json`、`vendor/genoffice/packages/orgmesh-docs-runtime/{package.json,tsconfig.json,src/contracts.ts}`、`vendor/genoffice/UPSTREAM.json`、`vendor/genoffice/apps/docs/vite.browser.config.ts`、`vendor/genoffice/apps/docs/src/renderer/browser-main.tsx`、`vendor/genoffice/apps/docs/src/renderer/platform/host.ts`、`vendor/genoffice/apps/docs/tests/browser-host.test.ts`、`tools/check_genoffice_browser_boundary.mjs`。
- Modify: vendored root `package-lock.json` 仅登记新契约 workspace；vendored `apps/docs/package.json`、`src/renderer/App.tsx`、`main.tsx`、`env.d.ts`、`file-actions.ts`、`ui-theme.ts`、`ai/AiPanel.tsx`。其他宿主依赖只能列入本项生成的 `docs/genoffice-host-inventory.md` 后再改；不得扩及 Sheets、Slides、Shell 或重构整个 App。
- Test: `web/tests/e2e/pages/GenOfficePage.ts`、`web/tests/e2e/orgmesh-documents/browser-port.spec.ts`。

**Interfaces:** 产出 DocsHostPort、`mountDocs(host: DocsHostPort): Promise<() => void>` 与 `/office/docs/index.html` 静态构建；测试 host 仅提供本地 fixture 数据。尚不连接模型或真实文档 API。

- [ ] 1. 在隔离树核对上游 SHA、LICENSE、lockfile 和安装脚本；记录原始 renderer、CLI DOCX 基线与宿主调用清单。按已锁依赖安装，不擅自升级；如必须执行非官方软件或需私有访问，停止报告。
- [ ] 2. 写 `opens_original_renderer_without_electron`、`round_trips_docx_without_external_requests` 的失败断言：`await expect(editor).toBeVisible(); expect(window.desktop).toBeUndefined(); expect(requests.some(isExternalDocumentUrl)).toBe(false)`。测试中打开原 UI、编辑中英文、保存并重新打开 fixture，侧栏保持可见。
- [ ] 3. 运行 `(cd web && bun run playwright tests/e2e/orgmesh-documents/browser-port.spec.ts)`，确认因浏览器入口或宿主依赖缺失失败，不能接受测试本身配置错误。
- [ ] 4. 实现 mountDocs 与最小 host 分离，保留原编辑器与面板视觉；网页模式禁用 AgentLoop、Electron 设置、PDF、模型供应商与本地字体权限入口。原桌面逻辑留在 desktop adapter，浏览器 bundle 禁止 Node/Electron 模块与任意 IPC。
- [ ] 5. 运行上游现有 `npm run typecheck -w @genoffice/docs`、新增 `npm run build:browser -w @genoffice/docs`、上述 Playwright 与 `node tools/check_genoffice_browser_boundary.mjs`；均须通过，浏览器 console 无未处理异常。另开 altChunk/外部图片样本，确认拒绝或安全显示，无外网。
- [ ] 6. 仅提交本项明列源码、来源信息及测试，提交名 `feat: port GenOffice Docs host to browser`；保留构建日志、截图和 host 清单供复核。

**Gate A:** 未通过“原界面无 Electron 打开、编辑、保存、重开”时停止后续任务，先报告具体依赖或保真障碍。不得用自行重写的编辑器代替过关。

## Task 2 建立受限 DOCX 候选执行器

**Files**
- Create: `vendor/genoffice/packages/orgmesh-docs-runtime/{src/selection.ts,src/candidate.ts,src/validate.ts,src/worker.ts,tests/candidate.test.ts,tests/limits.test.ts}`；扩展任务 1 的契约校验和 package scripts。
- Create: `backend/onyx/documents/{__init__.py,contracts.py,executor.py}`、`backend/tests/unit/orgmesh/documents/test_contract.py`。
- Modify: vendored root `package-lock.json`，只增加新 workspace 所需锁定项；复用上游 `packages/cli/src/formats/docx.ts`、`dom.ts` 与原格式继承工具，不复制新编辑 schema。

**Interfaces:** `validateSelection(bytes: Uint8Array, ref: SelectionRef): ValidatedSelection`；`createCandidate(bytes: Uint8Array, input: CandidateInput): Promise<{bytes: Uint8Array; result: CandidateResult}>`；Python `DocumentExecutor.create_candidate(base: bytes, request: CandidateInput) -> CandidateArtifact`。`ValidatedSelection` 含原文、from/to 和 schema_version；`CandidateArtifact` 含 bytes 与 CandidateResult。

- [ ] 1. 写 `counts_unicode_codepoints`、`rejects_stale_selection`、`preserves_untouched_parts` 及 `enforces_size_limits`：`expect(countCodePoints('中😀e\u0301')).toBe(4)`；`expect(() => validateSelection(bytes, wrongHash)).toThrow('STALE_SELECTION')`；`expect(after.unchanged_parts_ok).toBe(true)`；参数化 20 MiB、100 MiB、10000 entries、8000 code points 的边界与超限。
- [ ] 2. 运行新增 `npm run test -w @orgmesh/docs-runtime -- candidate.test.ts limits.test.ts` 与 `uv run pytest -q backend/tests/unit/orgmesh/documents/test_contract.py`，确认对应模块缺失的红灯。
- [ ] 3. 实现固定副本读写；replacement_text 按文本插入并继承原格式，不解释 HTML。拒绝复杂边界、加密/宏/路径逃逸、未支持 altChunk；禁止加载外部资源。重解析候选并比较选区外语义与附属 parts 哈希，变化异常不返回可接受结果。
- [ ] 4. 实现通过私有 Unix socket 的有界 JSON+二进制协议，`serveWorker(socketPath: string): Promise<() => Promise<void>>`。socket 目录 0700、socket 0600，仅 API 进程可连接；每次处理后清理临时目录。规划默认 worker RSS 上限 512 MiB、候选输出 20 MiB、单次执行 30 秒且不得越过 run 的 120 秒截止。没有隔离或超限时失败，不降级到主进程不受限执行。
- [ ] 5. 重跑上述测试、`npm run typecheck -w @orgmesh/docs-runtime`。fixture 覆盖正文、列表、表格外的正文、图像、页眉页脚、批注与修订，确认未编辑资源保持；限额、XXE/外部关系及脚本样本全部被拒绝或净化。
- [ ] 6. 只提交本项文件，提交名 `feat: generate bounded DOCX rewrite candidates`。

## Task 3 建立唯一文档写入与版本事务

**Files**
- Create: `backend/onyx/db/documents.py`、`backend/onyx/documents/{storage.py,service.py}`、`backend/onyx/server/documents.py`、`backend/alembic/versions/d7a10c46e921_add_orgmesh_documents.py`。
- Modify: `backend/onyx/db/models.py` 仅追加 Document/Version/Run/Proposal/Operation/Event ORM；`backend/onyx/main.py` 仅导入与注册新 router；`backend/onyx/configs/{app_configs.py,constants.py}` 仅新 feature flag 与文件 origin。
- Test: `backend/tests/integration/tests/orgmesh_documents/test_versions.py`、`test_acl.py`、`backend/tests/unit/orgmesh/documents/test_storage.py`。

**Interfaces:** `create_document(actor: ActorScope, bytes: bytes, metadata: DocumentCreate, key: str) -> DocumentSnapshot`；`save_version(actor, doc_id: UUID, expected: UUID, bytes: bytes, key: str) -> VersionResult`；`accept_proposal(actor, proposal_id: UUID, expected: UUID, key: str) -> VersionResult`；`restore_latest_ai(actor, doc_id: UUID, expected: UUID, key: str) -> VersionResult`。ActorScope 由现有认证与租户上下文构造；DocumentCreate 只含 title、可空 project_id/source_chat_id。

- [ ] 1. 写真实 PostgreSQL 测试 `test_concurrent_save_cas`、`test_accept_retry_is_idempotent`、`test_restore_preserves_history`：`assert sorted(statuses) == [200, 409]`；相同幂等键重试 `assert first.version_id == retry.version_id`；`assert count_new_versions() == 1`；恢复后 `assert restored.content_hash == parent.content_hash` 且旧历史仍在。
- [ ] 2. 运行 `uv run pytest -q backend/tests/integration/tests/orgmesh_documents/test_versions.py backend/tests/integration/tests/orgmesh_documents/test_acl.py`；应因未实现端点失败。不能把 SQLite 或 mock 行锁当作并发证据。
- [ ] 3. 按当前迁移图确定已有 head 后设置本迁移 down_revision，先记录 revision/heads，禁止自动合并现存分支。所有 SQL 在 db/documents.py；owner/tenant 外键与检查、一个文档一个 active run、幂等唯一约束、proposal 接受唯一性在 DB enforce。
- [ ] 4. 实现私有不可变文件对象适配，复用 FileStore 但不得先写“版本已完成”再上传。对象哈希校验成功后事务锁行、幂等比较、版本 CAS、追加记录；blob 失败不推进 current_version。跨 owner/tenant 的对象、版本、项目与会话统一不可见；来源访问失效时隐藏链接。
- [ ] 5. 重跑两组集成测试及 storage 单测；覆盖响应丢失、对象成功而事务失败、重复 accept/reject 竞争、已编辑后恢复拒绝。新增 flag `ORGMESH_DOCUMENTS_ENABLED=false` 时新路由不可用，旧 API 行为不变。
- [ ] 6. 只提交本项字段与文件，提交名 `feat: persist owned documents and guarded versions`；不得一并提交原 Presenton/Go 暂存内容。

## Task 4 把浏览器宿主接入真实文档与历史

**Files**
- Create: vendored `apps/docs/src/renderer/platform/{browser-host.ts,document-session.ts}`；`web/src/sections/workspace/documents/{DocumentEditor.tsx,DocumentHistory.tsx,api.ts,types.ts}`；`web/src/app/app/tools/documents/[id]/page.tsx`；`tools/build_genoffice_browser.mjs`。
- Modify: `web/src/sections/workspace/WorkspaceTools.tsx` 仅新增入口；九个 `web/src/i18n/messages/*.json` 增加同 namespace；原 renderer 的 file-actions 调 host；不改 Presenton 页面。
- Test: `web/src/sections/workspace/documents/document-session.test.ts`、`web/tests/e2e/orgmesh-documents/manual-edit.spec.ts`。

**Interfaces:** 实现任务 1 的 DocsHostPort 的 open/read/save/restore，其他方法在任务 5 后接入。`DocumentSession = {documentId, versionId, localGeneration, dirty, ownerKey}`；`adoptVersion(result, requestEpoch): boolean` 仅接受同文档、同 owner、仍有效的返回。

- [ ] 1. 写 `retains_dirty_state_on_conflict`、`ignores_old_epoch`、`clears_cache_on_owner_change`：`expect(session.dirty).toBe(true)` 在保存 409 后仍成立；`expect(adoptVersion(oldResult, oldEpoch)).toBe(false)`；退出切换用户后 `expect(cachedDocuments).toHaveLength(0)`。
- [ ] 2. 运行 `(cd web && bun run test -- document-session.test.ts)` 与对应 `bun run playwright .../manual-edit.spec.ts`，确认红灯。
- [ ] 3. 实现同源 frame 与静态资源构建，Vite base 为 `/office/docs/`，浏览器入口 `/office/docs/index.html`。上传/下载只走认证 API；保存进行 CAS；版本历史 owner-scoped，显示版本、时间、操作与有权访问的来源。
- [ ] 4. 增加 BFCache pageshow 恢复、401/403、文档切换与用户切换清理。只返回已授权字节；冲突保持本地内容可复制或下载，不自动刷新覆盖。CSP 禁止连接外部文档资源，不申请本地字体权限。
- [ ] 5. 重跑本项测试、`bun run types:check`、`bun run lint`；实际打开、改文、保存、下载、重开后 content_hash 与版本一致。
- [ ] 6. 局部提交 `feat: connect browser Docs to owned document history`。

**Gate B:** 真实 API 的普通编辑与版本 CAS、DOCX 往返保存验收通过后，才接 AI；界面与文档能力失败时不消耗模型额度调试。

## Task 5 接通 Onyx 运行与持久事件

**Files**
- Create: `backend/onyx/documents/{onyx_runtime.py,events.py,run_service.py}`；`backend/onyx/tools/tool_implementations/documents/{read_selection.py,propose_rewrite.py}`；`backend/onyx/background/celery/tasks/documents.py`。
- Modify: `backend/onyx/chat/process_message.py` 仅新增内部可空 DocRunBinding 传递与工具集分支；`backend/onyx/tools/tool_constructor.py` 新增服务端专用构造函数；`server/documents.py` 增加 run/status/event/cancel 路由；`backend/onyx/background/celery/apps/primary.py` 注册文档任务，`backend/onyx/background/celery/tasks/beat_schedule.py` 注册恢复扫描，沿用 primary 队列与 expires。
- Test: `backend/tests/unit/orgmesh/documents/test_onyx_adapter.py`、`backend/tests/integration/tests/orgmesh_documents/test_runs.py`、`test_events.py`。

**Interfaces:** `start_run(actor, doc_id: UUID, selection: SelectionRef, instruction: str, key: str) -> RunRef`；`construct_document_tools(binding: DocRunBinding, emitter: Emitter) -> dict[int, list[Tool]]`；`execute_document_run(binding: DocRunBinding) -> None`；`append_event(run_id: UUID, event_type: EventType, payload: dict) -> RunEvent`。专用工具参数仅允许读上下文或 replacement_text，不能接受文件 ID、URL 或命令。

- [ ] 1. 写 `test_document_tool_allowlist`、`test_event_resume_exactly_once`、`test_cancel_fences_late_candidate`：`assert set(tool_names) == {'read_document_selection', 'propose_document_rewrite'}`；`assert len(unique_event_ids) == len(events)`；断流重放 `assert reconstructed == uninterrupted`；停止后迟到结果 `assert proposal_is_acceptible is False`。
- [ ] 2. 运行 `uv run pytest -q backend/tests/unit/orgmesh/documents/test_onyx_adapter.py backend/tests/integration/tests/orgmesh_documents/test_runs.py backend/tests/integration/tests/orgmesh_documents/test_events.py`，确认红灯。
- [ ] 3. 实现内部 binding 注入，沿用现有 Onyx 会话、模型设置、持久消息和停止机制；公开 SendMessageRequest 不接受文档权限声明。普通聊天 binding=None 的行为必须不变，专属工具不加到全局默认工具列表。
- [ ] 4. 后台调用显式传 tenant_id，Celery enqueue 设置 expires；Operation 同事务记录 queued 运行与待投递标记，恢复扫描只重投尚未领取的同一 run_id；任务原子领取，重复投递不重复调用模型。整体 deadline=创建时刻+120 秒；客户端断开不重启运行。进程异常后按租约和 deadline 转失败，迟到写入须通过 run fence。
- [ ] 5. 文档工具创建稳定 tool_execution_id，持久候选与事件；解析 Onyx 现行 NDJSON 流而非假设标准 SSE data 帧。支持 sequence 续传、24 小时 TTL、状态回读及鉴权失效断流；不使用仅测试环境的 ToolCallDebug。
- [ ] 6. 重跑本项全部测试，增加重复 enqueue、进程退出、120 秒 deadline、两个标签页 start 竞争、TTL 过期后结果回读。固定模型响应走已有测试工具；确认一般聊天流未改变后局部提交 `feat: drive document proposals through Onyx runs`。

## Task 6 原右侧面板中的差异 确认与安全撤销

**Files**
- Create: vendored `apps/docs/src/renderer/ai/{onyx-run-controller.ts,ProposalCard.tsx,proposal-state.ts}`、`tests/{onyx-panel.test.ts,proposal-state.test.ts}`。
- Modify: vendored `ai/AiPanel.tsx` 仅拆出 runtime/持久记录和回滚入口；`platform/browser-host.ts` 实现剩余 host 方法；原 Docs i18n catalog 增加文案。
- Test: `web/tests/e2e/orgmesh-documents/{rewrite.spec.ts,stale-preview.spec.ts}`，扩展既有 GenOfficePage POM。

**Interfaces:** `OnyxRunController.start(instruction: string, selection: SelectionRef): Promise<RunRef>`、`cancel(): Promise<void>`、`dispose(): void`；`canAccept(proposal: ProposalView, session: DocumentSession): boolean`。ProposalView 含 state、baseVersionId、documentId、requestEpoch、localGeneration、diff、proposalId。

- [ ] 1. 写 `rejects_changed_local_generation`、`waits_for_composition_end`、`ignores_previous_document_events`、`deduplicates_accept_clicks`：`expect(canAccept(p, {...s, localGeneration: s.localGeneration+1})).toBe(false)`；composition 未结束不能 start；页面切换后旧事件不得改动新面板；连续点击接受只发送同一幂等键的请求。
- [ ] 2. 运行 vendored Docs `npm run test -w @genoffice/docs -- onyx-panel.test.ts proposal-state.test.ts` 和 rewrite/stale-preview Playwright，确认红灯。
- [ ] 3. 发送前等待完整加载与输入法结束；先保存未保存内容，再从服务端已确认版本固定选区；若保存重解析改变了位置或选区原文哈希，要求重新选择，不能猜测映射。接管面板文字、工具状态、取消、会话恢复；浏览器模式不得构造本地 AgentLoop 或调用 Genspark 登录。
- [ ] 4. 实现逐段文本 diff 与只读候选预览、接受/拒绝。切换预览不污染原文档 dirty 状态；任意实际编辑使旧候选不可接受。确认期间锁定本次动作，采用 requestEpoch 避免旧响应污染；服务器已提交但页面切换后结果仍可从历史查到。
- [ ] 5. 旧 AI 快照回滚按钮改接 restore_latest_ai。最新 AI 版本且无未保存编辑才允许；后续编辑存在时不覆盖。停止、失败、过期与 stale 均有明确状态且不会自动重跑。
- [ ] 6. 重跑上述测试，覆盖中文输入法、emoji、延迟响应、双击、拒绝后重放事件、浏览器前后退及身份变化；复用原选区/聊天测试后局部提交 `feat: review and commit Word rewrite proposals`。

## Task 7 安全与故障收口

**Files**
- Create: `backend/onyx/documents/cleanup.py`、`backend/tests/integration/tests/orgmesh_documents/test_security.py`、`test_recovery.py`；`vendor/genoffice/packages/orgmesh-docs-runtime/tests/isolation.test.ts`；`deployment/docker_compose/docker-compose.orgmesh-documents-test.yml` 与 `deployment/Dockerfile.orgmesh-documents-runtime` 仅隔离测试环境的构建定义。
- Modify: 本期 storage、run_service、events、executor 与 browser-host 的限额、错误和恢复路径，不重构通用认证。

**Interfaces:** `reconcile_document_runs(now: datetime) -> RecoveryCounts`、`expire_document_candidates(now: datetime) -> ExpiryCounts`。两类结果只含计数，不含正文。未引用对象必须记录独立候选/操作归属与创建时间后才能清理；已接受版本永不由候选清理删除。

- [ ] 1. 写 `test_foreign_objects_hidden`、`test_expiry_keeps_accepted_version`、`test_recovery_does_not_repeat_llm`、`worker_cannot_connect_to_network`：foreign tenant/owner 的文档、历史、字节、proposal 与 event 均 404；关闭 flag 不可创建；`assert completed_version_exists_after_expiry`；`assert llm_calls_after_reconcile == llm_calls_before`；资源隔离测试中 DNS/外网连接失败。
- [ ] 2. 运行 `uv run pytest -q backend/tests/integration/tests/orgmesh_documents/test_security.py backend/tests/integration/tests/orgmesh_documents/test_recovery.py` 及 runtime isolation.test，确认红灯。
- [ ] 3. 实现安全错误映射：身份过期 401；无权对象 404；版本/幂等/active-run 冲突 409；过期游标 410；格式与选区不支持 422；大小限制 413。错误不泄露其他用户对象状态。CSP、净化、日志脱敏与后台租户传播同时验证。Node 测试容器 network_mode=none、只读根目录、cap_drop=ALL、no-new-privileges、512 MiB 上限，仅挂载私有 socket 与 tmpfs，不挂载数据库或用户凭证。
- [ ] 4. 实现恢复扫描：事务与对象失败不提升版本；幂等键能回读完整结果；过期候选不再接受；停止或超时后的工作结果无权发布。自动清理只处理本功能生成且没有版本引用的临时对象，并尊重存储保留策略。
- [ ] 5. 重跑本项用例与任务 2、3、5 的失败矩阵，记录输入限额与 worker RSS/时限确实受控，不只校验配置值；局部提交 `test: harden document isolation and recovery`。

## Task 8 完整验收与兼容检查

**Files**
- Create: `web/tests/e2e/orgmesh-documents/recovery.spec.ts`、`backend/tests/integration/tests/orgmesh_documents/test_compatibility.py`、`docs/genoffice-word-validation.md`。
- Modify: 仅修复本期测试揭示的问题，修复后重跑归属任务和整个切片。不执行部署或推送。

**Interfaces:** 产出一份逐项记录 passed/failed/not-run、实际命令、环境、基线 SHA 与限制的验收报告；不新增公开 API。

- [ ] 1. 先写 `completes_word_rewrite_and_restore`、`keeps_later_manual_edits`、`recovers_lost_accept_response` 的用户级失败用例：打开自有文档→选区改写→预览→接受→刷新→下载→撤销→重开；另测拒绝不变更、后续手动编辑阻止旧建议与旧撤销、返回丢失后查询成功版本。
- [ ] 2. 运行 `(cd web && bun run playwright tests/e2e/orgmesh-documents)`；所有交互通过 POM，使用 auto-retry 断言，不用长 sleep 伪造稳定。
- [ ] 3. 运行 `uv run pytest -q backend/tests/unit/orgmesh/documents backend/tests/integration/tests/orgmesh_documents`；运行两个 vendored workspace 的 test/typecheck、浏览器边界检查、`bun run types:check`、`bun run lint` 与 `bun run build`。完整缺依赖时记录 not-run，不把局部检查表述为全通过。
- [ ] 4. 在单独临时树应用已审定的 Presenton/Go 补丁，运行其既有定向回归并比较新 feature flag 关闭时的旧 API。迁移图不自动合并；兼容失败定位本期冲突后交复核，原暂存树不得改变。
- [ ] 5. 用固定模型响应完成所有验收；真实 Onyx 模型只做一次小文档 smoke，沿用已授权模型配置，若需新凭证或付费额度先询问。保存原界面截图和 DOCX fixture 往返验证结果。
- [ ] 6. 全分支复核源码、依赖、权限与验收证据。最后局部提交 `docs: record Word integration validation`；交付补丁与运行说明，保留 flag=false。不声称已经部署。

## 依赖顺序与经济执行方式

主顺序为 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8。任务 2 的纯 fixture 与任务 3 的 schema 测试可准备并行，但 Gate A 通过前不实现后台产品路径，避免浏览器不可移植时浪费工作。

推荐 Native：在一个隔离执行会话内按此顺序完成，Gate A 与 Gate B 必须给出实测证据，最后进行一次独立全分支复核。接口依赖很紧，复用上下文较省额度。另一选择是每项实现后独立复核再继续，额度更高但中途反馈更多。用户须审阅本计划并选择方式，之后才开始实施。

## 自审结果与当前验证状态

Spec 的界面保留、浏览器适配对应任务 1/4；内容与版本对应 2/3；Onyx 与流生命周期对应 5；预览/确认/安全撤销对应 6；安全与恢复对应 7；全部验收对应 8。五项 Review Focus 已分配具体测试。类型、限额、唯一写入与先幂等后 CAS 的顺序一致。

本次只撰写计划，没有导入 GenOffice checkout、安装产品依赖或执行以上产品测试。所有命令均是实施时的验证步骤，不是已通过记录。既有源码路径已核查；新文件与接口是本计划的明确建设范围。
