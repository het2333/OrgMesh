# OrgMesh 企业知识工作台

基于 Onyx Community v4.8.1（MIT 路径），保留 OrgMesh 品牌和 Onyx 来源标识。使用 Python、Next.js、PostgreSQL、OpenSearch 和 Celery，无需 Rust 重写。

当前本地地址：[http://localhost:3090](http://localhost:3090)。端口绑定 127.0.0.1，本地入口共用所有者身份。Docker 已分配 12 GiB 内存和 128 GiB 磁盘。当前运行完整检索与同步栈，已从 Lite 升级。

## 已提供的 P0/P1 能力

- 首页、独立搜索、Agent 目录和工作区设置使用真实 Onyx API；企业配置入口为 `/admin/orgmesh`。
- 侧边栏“工具”入口为 `/app/tools`。演示文稿支持中文创建、参考文档上传、作品列表、平台内编辑、自动保存及 PPTX/PDF 导出。
- 社区版独立搜索 `/api/orgmesh/search` 不需要聊天模型 Key；关键词检索和本地向量混合检索保留权限检查。
- 飞书连接器读取文档、知识库、云空间文件、表格及基础多维表格，支持增量同步和完整枚举后的删除处理。权限请求或目录枚举失败会停止对应批次。
- 飞书文档权限覆盖检索、预览、Agent 附件和历史会话。需要经过验证的独立员工账号及新鲜通讯录映射；共享连接器不能扩大飞书源权限。
- DeepSeek、通义千问预设与真实流式输出/工具调用检测。外部服务使用有效凭据；本地模型可免 Key，失败信息隐藏密钥。
- CJK 索引、持久化企业词表、本地中文 PDF OCR 和表格文字提取。当前本地嵌入模型为 `intfloat/multilingual-e5-small`（384 维）。
- 制度问答、员工入职、项目周报三个原生 Agent 模板。重复安装保留定制内容；有可用知识库时才启用原生搜索工具。本地三个 Agent 已绑定明确标注的合成验收知识集与 SearchTool，使用企业资料前请在编辑器替换知识集。
- 绑定知识库的默认模板先执行知识搜索。模型未调用工具或搜索失败时停止回答；定制提示词和提醒保留原生行为。默认模板使用普通问答模式。
- 新安装的模板使用原生系统提示，任务逐项引用实际检索原文。缺失的材料、时限、审批人和项目进展标为待确认。

当前默认聊天模型及三个 Agent 已切换为 DeepSeek 官方 API 的 `deepseek-chat`。密钥通过原生接口加密保存，管理接口返回脱敏值。飞书和企业 SSO 仍待提供企业配置。

P1 本地开发与验收已完成。三个 Agent 首先使用本地 Qwen，通过原生聊天 API 完成真实搜索、流式回答、引用保存和历史读取，耗时分别为 28.70、137.84、203.27 秒。随后使用 DeepSeek API 复测同一合成知识集，三次分别用时 6.70、6.62、6.56 秒，回答、引用和历史读取均通过。页面已验证 DeepSeek 模型名称、回答及来源面板。这些单次数据不代表企业并发性能。

最终回归测试 193 项、网关检查 6 项通过。此前同一部署的数据库权限检查 19 项、默认模板检查 9 项通过。本地模型记录见 `plans/agent-answer-live-results.json`，当前 DeepSeek 记录见 `plans/deepseek-live-results.json`；阶段记录见 `plans/2026-09-30-orgmesh-p1.md`。企业语料质量、目标并发和生产部署仍需单独验收。

## 本地启动与构建

需要 Docker Desktop、Docker Compose 2.24.4+；前端构建需要 Node.js 24 和 Bun。现有配置保存在被 Git 忽略的 `deployment/docker_compose/.env`，请保留密钥与数据卷。

```bash
./onyx.sh                         # 启动并等待健康
./onyx.sh ps                      # 查看服务
./onyx.sh logs --tail 100          # 查看日志
./onyx.sh down                    # 停止，保留数据卷
```

当前 `.env` 使用：

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.orgmesh.yml:docker-compose.orgmesh-full.yml:docker-compose.orgmesh-access.yml
ONYX_BACKEND_IMAGE=orgmesh-backend:local
ONYX_WEB_SERVER_IMAGE=orgmesh-web:local
ORGMESH_LOCAL_ACCESS=true
```

更新源码后构建并重建服务：

```bash
docker build -f deployment/Dockerfile.orgmesh-backend -t orgmesh-backend:local .
./deployment/build_orgmesh_web.sh
./onyx.sh up -d --no-build --wait api_server background web_server nginx
docker exec orgmesh-nginx-1 nginx -s reload
python3 deployment/verify_orgmesh.py
```

重建 API 容器后，重新加载网关以解析其当前 Docker 地址。

本地核心服务包括 API、前端、网关、PostgreSQL、OpenSearch、Redis、共享模型服务、后台任务和代码解释器。监督程序启用索引、文件处理与同步所需 worker；该开发机未启用独立监控和计划任务 worker。可查看：

```bash
docker exec orgmesh-background-1 supervisorctl -c /etc/supervisor/conf.d/supervisord.orgmesh.conf status
```

本地网段 `172.16.249.0/24`，项目名 `orgmesh`，数据卷以 `orgmesh_` 开头。备份时同时保留配置密钥和数据卷。`down -v` 会删除卷，日常停止服务不要添加 `-v`。

## 本机直达入口

`deployment/bootstrap_orgmesh.py` 通过原生账号和个人访问令牌接口创建本地所有者。凭据写入被 Git 忽略的 `.orgmesh-local/`（目录 0700，凭据 0600），不输出密钥。脚本拒绝覆盖已有工作区账号。

直达网关只用于单人本机环境，拒绝其他 Host/Origin，登录和注册页返回工作台。前端通过运行时标记隐藏本地退出入口；私有部署保留正常登录与退出。

恢复本地独立登录时，移除 `docker-compose.orgmesh-access.yml`，设置 `ORGMESH_LOCAL_ACCESS=false`，重建 API、前端与网关。账号和知识库数据保留。切勿把共享所有者网关暴露到企业网络。

## 独立企业私有部署

私有配置使用独立 Compose 项目 `orgmesh-private` 和独立数据卷，不加载本地所有者令牌或 `.env`。默认使用独立账号、企业邮箱域限制、邮箱验证和 TLS。企业可以在原生 SSO 提供商页面进一步配置其身份系统；实际 IdP 联调需要企业配置。

先把构建后的镜像及本项目部署文件交付到目标服务器，准备真实证书目录，包含 `tls.crt` 和 `tls.key`。然后生成专用配置：

```bash
python3 deployment/init_orgmesh_private.py \
  --origin https://knowledge.example.com \
  --email-domains example.com \
  --tls-directory /absolute/path/to/certificates \
  --bind 0.0.0.0 --port 443
```

请将示例域名、证书目录和端口替换为企业实际值。脚本生成 0600 的 `deployment/docker_compose/.env.private`，包含独立随机密钥，拒绝覆盖已有文件，不打印凭据。`USER_AUTH_SECRET` 用于认证签名，`ENCRYPTION_KEY_SECRET` 用于凭据加密；备份时保留这些密钥。

**首次管理员注册前，必须在 `.env.private` 配置 SMTP 邮箱验证服务**：`SMTP_SERVER`、`SMTP_PORT`、`EMAIL_FROM`、`SMTP_USER`、`SMTP_PASS`，按服务器要求设置 `SMTP_STARTTLS`。随后：

```bash
./onyx-private.sh
./onyx-private.sh ps
./onyx-private.sh logs --tail 100
```

默认监听 `127.0.0.1:3443`，网段 `172.16.248.0/24`；生成配置时指定 `--bind`、`--port`、`--subnet` 可调整。公开 origin 必须与实际 TLS 访问地址对应。当前未在远端执行部署；需要企业服务器、域名、证书和邮箱服务。

## 飞书与模型接入

在“添加连接器 → 飞书”保存企业应用 App ID/App Secret，填写企业地址及文件夹 Token/知识库空间 ID。企业应用需要官方内容读取、权限读取、用户及部门查询权限和对应可见范围。高级多维表格角色权限暂不支持，无法确认的访问会拒绝。

在 `/admin/orgmesh` 选择相同飞书凭据，启用通讯录同步并执行首次同步。员工登录邮箱必须与飞书企业邮箱对应。通讯录约每五分钟更新；超过十五分钟未刷新时，飞书访问拒绝。文档权限也按实际获取时刻计算有效期，队列等待不会延长授权。

在“语言模型”选择 DeepSeek 或通义千问预设，输入实际 API Key、模型名和服务地址，然后执行能力检测。当前工作区已配置下述聊天模型，可直接问答。

## 聊天模型

当前默认模型为 DeepSeek `deepseek-chat`，官方服务地址为 `https://api.deepseek.com/v1`，界面名称为“DeepSeek Chat”。提供商 ID 和模型配置 ID 均为 2；三个 Agent 均绑定该模型。真实流式输出、工具调用和三个 Agent 问答已通过。检索与嵌入仍在本地运行，聊天生成调用 DeepSeek 服务并按其 API 计费。

本地 `Qwen3-4B-Instruct-2507` 保留为备用，采用 Q4_K_M 量化和 8192 token 上下文。Docker Desktop Model Runner 使用本机 Metal GPU。界面名称为“Qwen3 4B 本地模型”，无需外部 API Key。切换后已卸载出内存，模型文件和提供商配置保留；手动选择后可由运行器重新加载。

原生 OpenAI-compatible 服务地址为 `http://model-runner.docker.internal/engines/v1`，仅供容器内部调用。未开放宿主机模型端口。模型使用以下不可变 ID，避免当前 Docker 模型客户端的标签兼容问题：

```text
sha256:037ead90b7bd21678b827f5e9b8d4d61608a03276d34404efb9d145deb28b694
```

权重来自官方 Docker `ai/qwen3:4b-instruct-2507-q4_K_M`，已校验 SHA256。当前运行器不识别该远端包的新配置格式，因此使用同一 GGUF 权重在本机导入。原始权重保存在被 Git 忽略的 `.orgmesh-local/models/`。模型位于 Docker Desktop 的独立存储，迁移机器时须同时迁移或重新导入。

流式输出与真实工具调用已通过原生能力检测。本地 4B 模型用于开发与链路验收；企业效果和并发需要企业语料及目标模型另行评估。

## 中文检索验收

样本入口名为“OrgMesh P1 检索验收样本（合成资料）”，包含 8 份文本及 3 份中文 PDF，明确标注为验收样本。11 份文档已通过真实文件连接器完成解析、OCR、向量生成与索引，扫描和混合 PDF 可以检索到中文文字。

12 道合成题经前端 `/api/orgmesh/search` 验证，关键词检索的 Recall@5 和 Recall@10 均为 100%；词表前 Recall@1 为 87.5%、MRR 为 0.9375，词表后为 95.8% 和 1.0。相关文档可能有多个，Recall@1 与 MRR 定义不同。索引还包括 3 份 PDF 干扰项；这些小样本分数只用于本地链路验收，不代表企业语料上的效果。

语料、词表、评估脚本与指标说明位于 `tools/evals/chinese/`；摘要结果见 `plans/chinese-live-results.json`。可用同一用户、同一语料进一步比较混合检索和重排模型。

OCR 限制：50 MiB 文件、20 个 OCR 页面、每页 8 百万像素/15 秒、每份文档 90 秒；缺少语言数据或超时可能使扫描内容不可用，应查看日志。本地镜像已安装 `chi_sim` 和 `eng`。

## 参考

- [Glean AI Assistant](https://www.glean.com/ai-assistant)
- [Glean Enterprise Search](https://www.glean.com/enterprise-search)
- [Glean Agent Library](https://www.glean.com/ai-agents/agent-library)
- [Glean 用户快速入门](https://docs.glean.com/user-guide/about/end-user-quick-start-guide)
- [Onyx 部署说明](https://docs.onyx.app/deployment/overview)

界面参考核对日期：2026-09-30。Glean 部分功能分批开放，OrgMesh 当前支持范围以本文件与实际配置为准。


## 演示文稿工具

Presenton 以私有服务接入。平台提供创建页、持久化任务和作品列表。编辑器沿用完整幻灯片编辑和导出运行库。用户无需另建账号。每次请求由平台认证，再获得对应用户的短期 Presenton 会话。作品、上传文件和导出文件仍按用户检查归属。

模型请求经过平台的 LiteLLM 转发。转发重新检查用户和默认模型权限。DeepSeek 密钥只保存在平台加密存储内。Presenton 使用有期限、限定用途的用户令牌，配置文件没有模型密钥。

目前支持中文、通用模板、3–20 页。参考文档支持 PDF、DOCX、PPTX、TXT，最多 5 个文件、合计 20 MiB。任务和作品在服务重启后保留；重启时未完成的任务会标为失败。暂未启用 AI 图片生成和依赖视觉模型的模板重建。

构建和启动本机集成：

```bash
bash deployment/build_orgmesh_presenton.sh
python3 deployment/enable_orgmesh_presenton.py
./onyx.sh up -d --no-build --wait presenton api_server web_server nginx
```

部署前须构建包含本项目改动的后端和前端镜像。构建脚本使用 `integrations/presenton/upstream.lock.json` 指定的源码版本和基础镜像。运行配置写入已有的、未纳入版本控制的 env 文件。备份时保留 `ORGMESH_PRESENTON_SECRET` 和 `orgmesh_presenton_data` 卷。Presenton 不开放宿主机端口。

企业私有部署可在已有配置上运行：

```bash
python3 deployment/enable_orgmesh_presenton.py --env-file deployment/docker_compose/.env.private
./onyx-private.sh up -d --no-build --wait presenton api_server web_server nginx
```

本机 Presenton 内存上限为 3 GiB。平台模型仍使用 DeepSeek API；此服务不加载本地大语言模型。任务与作品时间默认显示中国标准时间；构建时设置 `NEXT_PUBLIC_ORGMESH_TIMEZONE` 可改用其他 IANA 时区。


## 公开仓库与验证范围

仓库首页为 `README.md`；本文件保留本机部署记录。文中的 `plans/` 文件只在开发机保留，不随仓库上传。

P1 记录使用合成资料。企业语料、企业 SSO 和目标并发需要单独验收。Presenton 的最终页面下载、PDF 导出和短文本 AI 编辑验收仍待完成；当前开发机资源压力导致部分服务不健康。

原有 Onyx 工作流归档于 `.github/upstream-workflows/`，适配 OrgMesh 后再启用。
