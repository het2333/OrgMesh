# OrgMesh 第一期企业服务实施计划

**Goal:** 在云端完成独立 Go 企业服务的第一期代码和验证，交付品牌配置、配置变更审计和用量统计。
**Architecture:** 保留 Next.js 和 Python AI 主流程。Python 同源接口校验身份，再通过私有本机套接字调用单个 Go 服务。Go 独占新增数据表，Python 只读现有用量。
**Tech Stack:** Go 1.27.1、标准库 HTTP、pgx v5.11.0、PostgreSQL；现有 Python 3.13、FastAPI、SQLAlchemy、Celery；现有 React、Next.js、Opal、next-intl。
**Spec:** 同目录配套设计位于 docs/superpowers/specs/2026-10-12-orgmesh-enterprise-phase1.md，对应已批准的 OrgMesh-Go-phase1-design.txt。

## Global Constraints

- “第一期不做：硬配额拦截、付费订阅、用户组权限替换、SCIM、外部系统权限同步、全站历史日志迁移、任意分析脚本、自定义 HTML、Logo 上传服务、多租户自助开户。”
- “建议默认：先服务现有单组织部署；数据结构始终带组织标识；仅现有经过验证的全局管理员可管理本期功能；不增加新角色、长期凭据或外部服务接入。”
- “所有业务主键、唯一键和查询条件包含 tenant_id。”
- “Python 保持原有用户、会话、AI 用量与业务表的唯一写入责任；不允许 Go 直接修改它们。”
- “成功的品牌配置创建或修改与对应审计记录在同一个数据库事务提交；审计落库失败时该配置变更回滚。”
- “第一期不实施自动数据删除；正式使用前由用户确认留存、备份与访问策略。”
- 不复制或逐行翻译企业实现；保留复用代码的版权、许可及第三方署名。
- 不推送、不部署、不创建长期凭据或服务账号，不改变真实环境安全配置。
- 保留现有品牌补丁独立身份。本计划不自动合并该补丁，也不改动旧检出。

## Review Focus

1. 管理员使用受限 PAT：仍按 PAT 范围拒绝，不能因账号是管理员而放行。任务一验证。
2. 启用当天已有用量：不把整天旧值误当启用后增量。任务四、六验证。
3. 重试时配置版本已变化：同一操作重试返回原结果，不重复修改或写审计。任务二验证。
4. 删除用户、清零、无痕记录：不丢系统归属、不重现个人身份、不叠加旧快照。任务四、五验证。
5. Go 故障并切换账号：不显示前一账号缓存，不回调旧企业接口。任务三、六、七验证。

## Issues to Address

先交付两个可单独验收的成果：
- 交付 A：品牌配置与事务审计，对应任务一至三。
- 交付 B：基于完整窗口快照的统计，对应任务四至六。
- 任务七验证集成和恢复，不扩大功能范围。

只有实施计划通过审阅后，才进入下列开发步骤。每项遵循先失败测试、最小实现、通过测试、局部提交。本文只有接口和验证要求，没有产品实现代码。

## Important Notes

### 已核实的基线

2026-10-12 核对 GitHub main 与 git ls-remote，均为 dfd891f3d4e864f8abeef45c6b09469bf2a7809e。
已建立独立的稀疏云端检出，分支为 design/orgmesh-enterprise-phase1。旧检出 ed2a290 未改动。
实施时从此固定基线创建 feat/orgmesh-enterprise-phase1；若 main 有更新，先比较相关差异，不能静默换基线。
现有品牌补丁仍单独保存，未应用到该分支。

已阅读根目录、backend、web 的 AGENTS.md 和 CONTRIBUTING.md。新 Python 查询只放 db 目录；新 API 使用类型签名和 OnyxError；不新增不必要的 async 流程。
网页使用 Opal、SWR 和 next-intl；所有新增文案覆盖 ar、de、en、es、fr、ja、ko、pt、zh 九个目录文件。
现有 Go 历史服务只提供受限本机 IPC，本期另建 services/orgmesh-enterprise 模块，不改写历史服务。

### 核实后确定的接入点

- 权限：backend/onyx/auth/permissions.py 的 require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)，包含 PAT 范围检查。
- 组织：shared_configs.configs 的 MULTI_TENANT、POSTGRES_DEFAULT_SCHEMA 和 contextvars.get_current_tenant_id。
- 用量：backend/onyx/db/models.py 的 UserUsage，同时含 USER 与 SYSTEM 行。
- 用量是 UTC 日窗口；USER_USAGE_BUCKET_SECONDS 为 86400。启用后的统计从下一个 UTC 零点开始。
- cost_cents 为 Numeric(18,6)。通过 Decimal 读取和字符串传输，不能经 float 往返丢精度。
- upsert 未显式更新 updated_at，因此不能用它作增量水位。
- 社区审计是日志输出。本期可靠审计只覆盖新服务成功提交的品牌变更。
- 网页 settings hook、服务端标题和图标入口仍有旧企业接口探测，任务三须显式切断本期路径。
- Go 使用 PostgreSQL 驱动 pgx v5.11.0，已核对官方发布页；不采用未固定的 latest 依赖。

### 当前未验证的运行条件

云盘约有 4.5 GiB 可用；保留至少 1 GiB，不做额外清理。
Python 3.13 已存在。当前 /usr/bin/go 不接受 Go 的 version 命令，不能当成有效 Go 工具链。
未发现 Bun、Docker、psql 或 initdb。没有启动应用、数据库或执行产品测试。
开发前按任务一做环境检查。安装只用官方来源及锁定依赖，并将缓存放可写工作区。
不执行完整 GPU/模型依赖安装，不自动获取 AWS 或其他秘密，不将凭据写进仓库。
本机套接字、临时数据库或浏览器若被执行环境拒绝，保留其他测试结果，并明确标记集成验收未通过。

## Implementation strategy

### 固定接口与配置

新增服务模块 services/orgmesh-enterprise，Go module 为 orgmesh.local/enterprise。
新增公开前缀 /api/orgmesh-enterprise/v1，由现有 Python API 挂载。
Go 只监听 /run/orgmesh-enterprise/enterprise.sock，开发和测试可传入工作区绝对路径。没有 TCP 回退。

新开关均默认 false：
- ORGMESH_ENTERPRISE_BRANDING_ENABLED：动态品牌读写。
- ORGMESH_ENTERPRISE_AUDIT_ENABLED：审计查询和页面。关闭它不关闭品牌写入的事务审计。
- ORGMESH_ENTERPRISE_USAGE_ENABLED：统计采集、查询和页面。

另设只读静态配置 ORGMESH_ENTERPRISE_STATIC_BRANDING_FILE；无文件使用已批准 OrgMesh 默认值。
其中只有名称、欢迎语、审核过的本地 Logo 资源 ID，不接受可执行 HTML 或远程抓取 URL。
静态文件来自启用前经确认的品牌配置；不能自动从旧企业服务迁移。
契约中的 RequestModel 和 ResponseModel 在 Python models.py 声明为具名请求与响应的判别联合；Go共享类型均定义于 internal/protocol，业务包不重定义字段。
第一期遇到 MULTI_TENANT=true 或当前组织不等于服务器配置组织时，拒绝开启，不假装支持多租户。
未来组织隔离的测试用两个独立配置实例，复用同一测试库，验证所有查询确实带组织条件。

对外接口：
- GET /branding：public BrandingView；开关关闭或服务不可用时返回静态配置及 source=static。
- PATCH /branding：BrandingPatch，包含 expected_version、name、greeting、logo_asset_id；仅管理员。
- GET /audit/events：AuditPage；仅管理员，默认50条、最多100条，日期范围最多90天。
- GET /usage/summary：UsageSummary；仅管理员，默认30天、最多最近90天，不输出邮箱或用户明细。
- GET /capabilities：仅返回本期三个开关与静态品牌版本，不包含敏感设置。
- Go 内部 /healthz 和 /readyz：仅运行状态，无配置或凭据。

Branding 字段上限：名称1至50个 Unicode 字符；欢迎语0至120个字符；Logo ID 必须在静态白名单内。
PATCH 要求 Idempotency-Key UUID。Python 将键、已认证用户、组织及操作派生成稳定 request_id。
同一 request_id 与相同内容返回原结果；不同内容返回409。字段校验失败422，无权限403，未登录401，不可用503。
字段上限和90天范围属于本计划的默认值，可在计划评审时调整。

可信上下文 Identity：version=1、tenant_id、actor_kind、user_id、operation、request_id、audience、issued_at、expires_at。
用户操作只传已通过检查的具体 operation，不传整个用户权限集合。worker 使用 producer 类型，不冒充用户。
受众固定 orgmesh-enterprise/v1；上下文最多有效5秒，每次内部调用重新生成。
浏览器提交的身份、角色、组织请求头一律不转发。匿名品牌读取只允许 branding.read。
Go 先验证套接字对端 UID，再验证上下文和操作。上下文不是可被公开端点接受的自签凭据。

套接字目录0700、文件0600、拒绝软链接与不安全旧文件；连接数上限32。
SO_PEERCRED 只证明 UID。相同 UID 下的进程必须都受信任。
若运行环境不满足该边界，不能开放网络端口补救；须先获得相应隔离或认证设置授权。

### 数据所有权

Go 迁移仅创建 orgmesh_enterprise schema：
- branding_configs：组织唯一配置、版本、修改时间。
- branding_receipts：组织、操作者、request_id 唯一，保存请求摘要及原响应。
- audit_events：组织、事件ID唯一，保存操作、结果、版本变化、字段名和request_id，不存完整欢迎语或密钥。
- usage_sync_state：组织与覆盖范围、修订号、租约和已发布版本。
- usage_staging、usage_batches：快照行及分块摘要，尚不可查询。
- usage_rows：发布后的当前快照，按组织和 source_row_id 唯一。

schema_migrations 为服务级迁移元数据，不存业务数据。
Go 只迁移、读取或写入上述命名空间。没有 Community 数据库访问适配器。
本地集成使用隔离的临时测试库；真实部署中的数据库身份和权限配置另行批准。

## 任务一 建立安全入口和契约

**Files**
- 新增 contracts/orgmesh-enterprise/v1.schema.json 与 fixtures/ 下的合法、越权、超限样本。
- 新增 services/orgmesh-enterprise/go.mod、go.sum、cmd/enterprised/main.go。
- 新增 internal/protocol/types.go、internal/ipc/listener_linux.go、listener_unsupported.go、internal/server/server.go。
- 新增 backend/onyx/orgmesh_enterprise/models.py、config.py、identity.py、client.py。
- 新增 backend/onyx/server/features/orgmesh_enterprise/api.py，修改 backend/onyx/main.py 注册路由。
- 测试：上述 Go 包的 *_test.go；backend/tests/unit/orgmesh/test_enterprise_contract.py、test_enterprise_identity.py、test_enterprise_client.py。

**Interfaces**
- Python authorize_enterprise_operation(user: User, operation: EnterpriseOperation, request_id: UUID) -> TrustedIdentity。
- Python EnterpriseClient.call(operation: EnterpriseOperation, identity: TrustedIdentity, payload: RequestModel) -> ResponseModel，使用同步 httpx、UDS、trust_env=False、禁止重定向。
- Go ValidateIdentity(identity Identity, operation Operation, now time.Time, tenant string) error。
- Go NewHandler(deps Dependencies) http.Handler；业务存储先用测试替身，不能以替身冒充持久化完成。

- [ ] 1. 检查工具链和剩余空间。记录 go version、Python、Bun 和数据库实际能力。没有正确工具链时先准备独立工具路径，不调用错误的 /usr/bin/go。
- [ ] 2. 写失败测试：test_pat_scope_denied、test_client_identity_headers_ignored、TestWrongTenantDenied、TestExpiredIdentity、TestUnsafeSocket、TestNonLinuxFailsClosed。
- [ ] 3. 运行新测试，确认因接口缺失或预期行为缺失失败，而非秘密缺失。
- [ ] 4. 实现契约、开关和入口。复用社区权限检查，不导入或动态加载企业实现。带作用域 PAT 即使属于管理员也须拒绝越权。
- [ ] 5. 限制普通请求和响应1 MiB、内部快照块1 MiB；未知字段、非有限数值、过期上下文和跨操作使用均拒绝。普通调用超时2秒，品牌读取失败只回退静态值。
- [ ] 6. 验证：在 Go 模块运行 go test ./internal/protocol ./internal/ipc ./internal/server；用项目 Python 环境运行上述三个 pytest 文件。每项测试为 PASS，不能以 skip 代替。
- [ ] 7. 局部提交：feat: add enterprise service contract and private transport。

## 任务二 实现品牌事务和审计存储

**Files**
- 新增 Go internal/store/postgres.go、migrate.go、migrations/001_branding.sql。
- 新增 internal/branding/service.go、repository.go；internal/audit/query.go。
- 新增 internal/store/postgres_integration_test.go、internal/branding/service_test.go、internal/audit/query_test.go。
- 补全任务一的 BrandingView、BrandingPatch、AuditEvent、AuditPage 契约。

**Interfaces**
- BrandingStore.Apply(ctx context.Context, identity Identity, patch BrandingPatch) (BrandingView, error)。
- BrandingStore.Read(ctx context.Context, tenant string) (BrandingView, error)。
- AuditStore.List(ctx context.Context, tenant string, query AuditQuery) (AuditPage, error)。
- Migrate(ctx context.Context, db *pgxpool.Pool) error；迁移有版本与校验和，不扫描或更改其他 schema。

- [ ] 1. 写失败测试：TestBrandingAndAuditAtomic、TestConcurrentExpectedVersion、TestRetryReturnsOriginal、TestIdempotencyBodyConflict、TestAuditTenantIsolation。
- [ ] 2. 运行 Go 包测试与隔离 PostgreSQL 测试，确认上述需求未实现。
- [ ] 3. 新增表与事务。先检查收据；再用 expected_version 原子更新；同事务写审计和结果收据。无字段变化时不增加版本或审计，仍保存幂等结果。
- [ ] 4. 审计只记录 branding.created 或 branding.updated、success、前后版本及变更字段名。读取和拒绝仍用脱敏日志，不宣称持久化全覆盖。
- [ ] 5. 游标固定使用 created_at 和 event_id 排序，并在每次查询重新应用 tenant_id。伪造其他组织游标不得返回其数据。
- [ ] 6. 验证：go test ./internal/branding ./internal/audit；ORGMESH_TEST_DATABASE_URL 指向临时测试库时运行 go test -tags=integration ./internal/store。测试须包括审计插入故障后的完整回滚。
- [ ] 7. 局部提交：feat: add atomic branding changes and audit history。

## 任务三 接入品牌页面和审计页面

**Files**
- 新增 web/src/lib/orgmesh-enterprise/types.ts、svc.ts、svcSS.ts、hooks.ts、staticBranding.ts。
- 新增 web/src/views/admin/OrgMeshBrandingPage.tsx、OrgMeshAuditPage.tsx。
- 新增 web/src/app/admin/orgmesh-enterprise/branding/page.tsx、audit/page.tsx。
- 修改 web/src/lib/settings/hooks.ts、svcSS.ts、types.ts，web/src/lib/app/svcSS.ts、components.tsx。
- 修改 web/src/sections/workspace/WorkspaceBrand.tsx、web/src/sections/workspace/WorkspaceHome.tsx 中实际品牌消费点；只改已核对的品牌字段。
- 修改 web/src/lib/admin-routes.ts、admin-sidebar-utils.ts、web/src/lib/adminNavLabels.tsx。
- 修改 web/src/i18n/messages/{ar,de,en,es,fr,ja,ko,pt,zh}.json。
- 新增页面对象 web/tests/e2e/pages/OrgMeshBrandingPage.ts、OrgMeshAuditPage.ts；spec不写内联定位器。
- 测试：web/src/lib/orgmesh-enterprise/branding.test.tsx；web/tests/e2e/orgmesh/enterprise-branding.spec.ts、enterprise-audit.spec.ts。

**Interfaces**
- useOrgMeshBranding(): BrandingState，提供 data、source、isLoading；它的故障不能变成全站 SettingsProvider 的致命错误。
- fetchOrgMeshBrandingSS(): Promise<BrandingView>，不缓存其他组织结果。
- useEnterpriseAudit(query: AuditQuery): AuditState，缓存键包含当前用户和组织。
- 通过 useSettings 的 appName、logoUrl 和新增 greeting 字段统一读取；不要把自有字段塞回旧 EnterpriseSettings 类型。

- [ ] 1. 写失败测试：test_branding_never_calls_legacy_endpoint、test_static_custom_brand_survives_outage、test_audit_requires_full_admin、test_branding_conflict_keeps_unsaved_input。
- [ ] 2. 运行定向 Jest，观察需求失败。不得使用仅检查字符串的测试代替组件状态验证。
- [ ] 3. 实现表单、版本冲突提示和只读审计列表。使用 Opal 组件、SWR、九语言键和现有全局管理员入口。
- [ ] 4. 分离核心 settings 的故障与新品牌故障。初始、登录前、Go 不可用和开关关闭都返回已确认的静态品牌；本期品牌路径不探测旧企业设置、Logo 或分析脚本。
- [ ] 5. 品牌 Logo 只引用已有审核资产；需要新默认资产时，仅取先前批准的 OrgMesh SVG。保留其来源记录，不套用整份品牌补丁。
- [ ] 6. 验证：cd web 后运行 bun run test --runInBand --runTestsByPath src/lib/orgmesh-enterprise/branding.test.tsx；再运行 bun run playwright tests/e2e/orgmesh/enterprise-branding.spec.ts tests/e2e/orgmesh/enterprise-audit.spec.ts。
- [ ] 7. 浏览器验收：保存、重复点击、冲突、刷新、返回、取消、登录中断、长名称、小屏及切换账号。交付 A 验收后再进行统计页面接入。
- [ ] 8. 局部提交：feat: add independent branding and audit administration。

## 任务四 实现可恢复的用量快照接收

**Files**
- 新增 Go internal/usage/types.go、snapshot.go、summary.go、repository.go。
- 新增 internal/store/migrations/002_usage.sql、internal/usage/snapshot_test.go、summary_test.go。
- 补全 contracts/orgmesh-enterprise/v1.schema.json 的内部快照与 UsageSummary。

**Interfaces**
- BeginSnapshot(ctx context.Context, identity Identity, coverage Coverage) (SnapshotLease, error)。
- StageBatch(ctx context.Context, identity Identity, lease SnapshotLease, batch SnapshotBatch) (StageAck, error)。
- CommitSnapshot(ctx context.Context, identity Identity, lease SnapshotLease, manifest SnapshotManifest) (PublishedSnapshot, error)。
- UsageStore.Summary(ctx context.Context, tenant string, query UsageQuery) (UsageSummary, error)。
- Coverage 为明确的 UTC [from,to) 范围；每个已提交快照是该范围完整替换，不是计数增量。

快照行保留 source_row_id、actor_kind、user_id 可空、system_attribution 可空、window_start、model、flow、provider、incognito、四类 Token 计数和 cost_cents 十进制字符串。
user_id 不用于快照主键，避免删除用户后的空 ID 冲突。API 汇总不输出 source_row_id、user_id 或邮箱。

- [ ] 1. 写失败测试：TestReplayDoesNotAdd、TestSameRevisionDifferentDigest、TestExpiredLeaseCannotCommit、TestCrashBeforePublish、TestResetRemovesOldRows、TestDeletedUserRemainsUser、TestDayBoundaryActivation。
- [ ] 2. 运行 Go 定向测试，确认尚未实现。
- [ ] 3. Go 在读取源数据前分配持久单调修订号和45秒租约。同组织只允许一个活跃同步。租约只是并发控制，不是外部认证凭据。
- [ ] 4. 每块最多1000行、1 MiB；一次完整快照最多100000行、64 MiB。超限拒绝整个快照并保留旧版，不能截断后发布。
- [ ] 5. 发布事务检查租约、所有块摘要、总行数及整体摘要。显式 complete=true 的范围才可替换其旧投影；上传中断不删除已发布行。空完整快照可正确反映来源清零。
- [ ] 6. 发布版本和同步游标原子提交。相同修订号与摘要的重试返回原结果；更旧或过期租约拒绝。服务重启后可重试或开始新修订并重新读取。
- [ ] 7. 汇总只接受实际覆盖的最近90天；分开 USER、SYSTEM ATTRIBUTED、SYSTEM UNATTRIBUTED 和 incognito。Token汇总只算input_tokens加output_tokens，缓存计数单列且不再相加。费用按来源 USD cents 精度计算，明确为来源估算。源表没有价格完整性字段，且未知价格可能记录0；页面必须提示“0可能表示缺少定价”，不能标记为免费或已结算。
- [ ] 8. 验证：go test ./internal/usage；go test -tags=integration ./internal/store。使用可控时钟测试 UTC 日界、45秒租约和超过120秒的 stale 状态。另测缓存Token属于输入Token子集：总Token只算input加output，不再加两类cache计数。
- [ ] 9. 局部提交：feat: add fenced usage snapshot publication。

## 任务五 实现只读采集和统计接口

**Files**
- 新增 backend/onyx/db/orgmesh_usage_snapshot.py。
- 新增 backend/onyx/orgmesh_enterprise/snapshot.py。
- 新增 backend/onyx/background/celery/tasks/orgmesh_enterprise_tasks.py。
- 修改 backend/onyx/background/celery/apps/primary.py、tasks/beat_schedule.py 和必要的任务名称常量。
- 补全 backend/onyx/server/features/orgmesh_enterprise/api.py 的统计接口。
- 测试：backend/tests/external_dependency_unit/orgmesh/test_enterprise_snapshot.py；backend/tests/unit/orgmesh/test_enterprise_snapshot_task.py；backend/tests/integration/tests/orgmesh/test_enterprise_api.py。

**Interfaces**
- read_usage_snapshot(*, tenant_id: str, start: datetime, end: datetime) -> UsageSnapshot。
- produce_usage_snapshot(*, tenant_id: str) -> None，使用 shared_task。
- get_usage_summary(query: UsageQuery, user: User) -> UsageSummary，路由依赖负责 FULL_ADMIN_PANEL_ACCESS 和 PAT 检查。
- 任务一的同步 EnterpriseClient 增加 begin、stage、commit 方法，与任务四契约一致。

- [ ] 1. 写失败测试：test_source_read_only、test_snapshot_decimal_exact、test_upsert_without_updated_at_is_detected、test_reset_and_null_user、test_missing_tenant_is_rejected、test_explicit_expiration。
- [ ] 2. 运行定向 pytest，确认需求失败。
- [ ] 3. 使用 get_session_with_tenant 建立新的 REPEATABLE READ、READ ONLY 事务，读取原始 UserUsage。查询只位于 db 模块；不使用按邮箱输出或按日再次聚合的导出接口。
- [ ] 4. cost_cents 在 SQL 读取阶段保留 Decimal，稳定排序后分块。先向 Go 申请租约，再读取同一一致性视图；不写源表，也不建 Python 导出游标表。
- [ ] 5. 每60秒采集启用起点至当前日末、最多最近90天的完整范围。首次启用记录 next UTC midnight，之后重启不能重置起点。只有显式启用才读取源数据。
- [ ] 6. Celery 使用明确队列、tenant_id、expires=55 和代码内45秒总期限。不能依靠 thread pool 无效的 soft_time_limit。失败下轮重新申请租约并重读；不无限重试。
- [ ] 7. 关闭统计开关后停止采集并隐藏查询入口。新接口不能由客户端指定组织；Go不可用返回503，不回调旧企业报表。
- [ ] 8. 验证：uv run --frozen --no-sync pytest backend/tests/unit/orgmesh/test_enterprise_snapshot_task.py backend/tests/external_dependency_unit/orgmesh/test_enterprise_snapshot.py；随后跑 test_enterprise_api.py。环境必须有已准备的锁定依赖；no-sync 失败不能掩盖为测试通过。
- [ ] 9. 局部提交：feat: add community usage snapshot adapter。

## 任务六 实现统计页面和隔离缓存

**Files**
- 新增 web/src/views/admin/OrgMeshUsagePage.tsx。
- 新增 web/src/app/admin/orgmesh-enterprise/usage/page.tsx。
- 补全 web/src/lib/orgmesh-enterprise/{types,svc,hooks}.ts。
- 新增 web/src/lib/orgmesh-enterprise/usage.test.tsx、web/tests/e2e/orgmesh/enterprise-usage.spec.ts、web/tests/e2e/pages/OrgMeshUsagePage.ts。
- 更新九个语言目录、管理员路由与标签。

**Interfaces**
- useEnterpriseUsage(query: UsageQuery): UsageState。
- UsageState 包含 data、coverage、lastPublishedAt、stale、unavailable、activationBoundary。
- 查询和缓存键必须包括已验证的当前用户、组织和日期范围。退出或组织变化清空旧数据。

- [ ] 1. 写失败测试：test_account_switch_clears_usage、test_no_snapshot_is_not_zero、test_user_system_separated、test_pre_activation_day_excluded、test_unknown_pricing_label。
- [ ] 2. 运行新 Jest 测试，确认需求失败。
- [ ] 3. 实现日期选择、分组 Token、费用和更新时间。仅展示聚合，不提供个人明细、CSV或原始聊天文本。
- [ ] 4. Go断线时只允许当前会话保留已取得结果，显示陈旧时间；没有结果时显示不可用。不能从第二套持久缓存取数。
- [ ] 5. 验证：bun run test --runInBand --runTestsByPath src/lib/orgmesh-enterprise/usage.test.tsx；bun run playwright tests/e2e/orgmesh/enterprise-usage.spec.ts。
- [ ] 6. 浏览器检查日期越界、无数据、首日等待、数据刷新、服务中断、返回和账号切换。交付 B 完成对账验收。
- [ ] 7. 局部提交：feat: add enterprise usage dashboard。

## 任务七 集成边界和恢复验收

**Files**
- 新增 deployment/Dockerfile.orgmesh-enterprise；deployment/docker_compose/docker-compose.orgmesh-enterprise.yml。
- 新增 services/orgmesh-enterprise/README.md、docs/orgmesh-enterprise-phase1-operations.md。
- 新增 tools/check_orgmesh_enterprise_boundaries.py。
- 新增 backend/tests/integration/tests/orgmesh/test_enterprise_recovery.py。
- 新增 web/tests/e2e/orgmesh/enterprise-regression.spec.ts。

**Interfaces**
- Compose 仅作为可审阅模板，无宿主机 TCP 服务端口。
- 只共享所需 UDS 路径；Go数据库仅指向自有 schema，身份/授权设置不得自动应用。
- 恢复入口是关闭三个新开关，保留新表、审计记录和静态品牌文件。
- 边界检查输出文件、依赖与失败原因，不能只靠字符串搜索声称无企业依赖。

- [ ] 1. 写失败测试：test_branding_without_audit_ui_still_records、test_disabled_features_no_source_reads、test_outage_does_not_break_chat、test_new_path_no_ee_import_or_http_call、test_reenable_no_double_count。
- [ ] 2. 检查新路径直接依赖、动态导入、路由调用和前端网络请求。使用现有社区模式且禁止加载 ee.* 的测试环境验证新接口；不声称整个存量应用已经完全移除企业模块。
- [ ] 3. 加入容器模板、健康检查、资源上限和启动失败说明。不得复制历史服务的 root 配置作为默认安全配置。
- [ ] 4. 在隔离测试库执行新建迁移和重复迁移；旧 schema 的结构与数据哈希不变。停止Go、模拟数据库故障，再关闭新开关。
- [ ] 5. 验证静态品牌恢复、数据表保留、采集停止、聊天与检索不回退。重新启用并重放快照，结果不重复。
- [ ] 6. 完整验证：Go模块 go test -race -tags=integration ./... 与 go vet ./...；定向 Python 外部依赖和集成测试；web 的 bun run test、bun run types:check、bun run lint、bun run build 及四个 enterprise Playwright 文件。
- [ ] 7. 使用既有测试夹具和模拟模型，不为本期申请真实 LLM 密钥。完整构建若需当前未授权的秘密或外部访问，报告具体项，不编造测试结果。
- [ ] 8. 最终记录每项 PASS、FAIL 或未运行原因，附源码补丁、版本、迁移摘要和恢复验证证据。局部提交：test: verify enterprise integration and recovery。

## Tests 和完成定义

交付 A 必须通过真实 PostgreSQL 的原子性与并发测试、PAT权限测试和品牌/审计浏览器测试。
交付 B 必须通过快照乱序、重复、重启、清零、更正及精确金额对账。
最终必须通过两个组织样本的负向隔离测试和故障恢复测试。
单元通过不等于集成通过；静态扫描不等于运行时不加载企业代码。
若当前云端不能启动数据库、套接字或浏览器，仍可交代码和其他证据，但不得称第一期完整验收。
不自动把新服务部署到用户真实环境，不修改任何真实账号、权限或凭据。

## 实施顺序和审阅决定

建议按任务一至七逐项实现，每项做独立检查，再做整体检查。权限、数据库和快照交接多，逐项检查更容易及时发现错误。
另一选择是连续实现后统一检查，往返较少，但较晚才发现集成问题。

请确认：
1. 本实施计划是否符合已批准的第一期范围？
2. 采用“逐项实现并独立检查”，还是“连续实现后统一检查”？

环境已经确定为云端，不再要求使用 Mac。当前文件仅为计划，尚未执行产品实现。

## 证据

固定基线：https://github.com/het2333/OrgMesh/commit/dfd891f3d4e864f8abeef45c6b09469bf2a7809e
社区权限：https://github.com/het2333/OrgMesh/blob/dfd891f3d4e864f8abeef45c6b09469bf2a7809e/backend/onyx/auth/permissions.py
原始用量模型：https://github.com/het2333/OrgMesh/blob/dfd891f3d4e864f8abeef45c6b09469bf2a7809e/backend/onyx/db/models.py#L6206
日窗口与用量写入：https://github.com/het2333/OrgMesh/blob/dfd891f3d4e864f8abeef45c6b09469bf2a7809e/backend/onyx/db/user_usage.py
已有本机IPC边界：https://github.com/het2333/OrgMesh/blob/dfd891f3d4e864f8abeef45c6b09469bf2a7809e/services/orgmesh-core/internal/historyserver/listener_linux.go
Go数据库驱动：https://github.com/jackc/pgx/releases/tag/v5.11.0

本计划依照业务需求、公开契约与允许复用的社区接口制定。没有把企业实现翻译为Go；也不声称已取得严格隔离式开发或法律免责结论。
